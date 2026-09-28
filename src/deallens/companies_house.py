"""Conservative read-only Companies House public API client.

Official docs: developer-specs.company-information.service.gov.uk
This client has no access to Store and cannot mutate transaction economics.
"""
import hashlib
import json
import math
import os
import re
import tempfile
import time
from datetime import date, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class CompaniesHouseError(ValueError):
    pass


class ResponseModel(BaseModel):
    # CH adds optional properties over time; retain them in typed responses.
    model_config = ConfigDict(extra="allow")


class CompanyProfile(ResponseModel):
    company_name: str
    company_number: str
    company_status: str
    type: str | None = None
    date_of_creation: date | None = None
    registered_office_address: dict[str, Any] = Field(default_factory=dict)


class CompanySearchItem(ResponseModel):
    title: str
    company_number: str
    company_status: str | None = None


class SearchResults(ResponseModel):
    items: list[CompanySearchItem]
    total_results: int = Field(ge=0)
    start_index: int = Field(ge=0)
    items_per_page: int = Field(ge=0)


class Filing(ResponseModel):
    transaction_id: str
    date: date
    type: str
    description: str
    category: str | None = None


class FilingHistory(ResponseModel):
    items: list[Filing]
    total_count: int = Field(ge=0)
    start_index: int = Field(ge=0)
    items_per_page: int = Field(ge=0)


class CompaniesHouse:
    BASE_URL = "https://api.company-information.service.gov.uk"

    def __init__(self, *, transport=None, cache_dir=None, cache_ttl=3600, max_attempts=3,
                 timeout=15.0, max_retry_wait=30.0, sleep=time.sleep, clock=time.time):
        key = os.environ.get("COMPANIES_HOUSE_API_KEY", "").strip()
        if not key:
            raise CompaniesHouseError("Set COMPANIES_HOUSE_API_KEY in the environment.")
        numeric_settings = (timeout, max_retry_wait, cache_ttl)
        if (isinstance(max_attempts, bool) or not isinstance(max_attempts, int)
                or not 1 <= max_attempts <= 5
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not math.isfinite(value) for value in numeric_settings)
                or timeout <= 0 or not 0 <= max_retry_wait <= 60 or cache_ttl < 0):
            raise ValueError("invalid retry, timeout or cache configuration")
        self.cache_dir = Path(cache_dir) if cache_dir is not None else Path(os.environ.get("DEALLENS_CACHE_DIR", ".cache/deallens/companies-house"))
        self.cache_ttl, self.max_attempts = cache_ttl, max_attempts
        self.max_retry_wait, self.sleep, self.clock = max_retry_wait, sleep, clock
        self.client = httpx.Client(base_url=self.BASE_URL, auth=(key, ""), timeout=httpx.Timeout(timeout),
                                   transport=transport, follow_redirects=False,
                                   headers={"Accept": "application/json", "User-Agent": "DealLens/0.1"})

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @staticmethod
    def _company_number(number):
        # Preserve leading zeros and reject paths/queries instead of interpolating them.
        number = number.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{8}", number):
            raise ValueError("company number must contain exactly eight letters/digits, including leading zeros")
        return number

    @staticmethod
    def _page(start_index, items_per_page):
        if isinstance(start_index, bool) or isinstance(items_per_page, bool) or not isinstance(start_index, int) or not isinstance(items_per_page, int):
            raise ValueError("pagination values must be integers")
        if start_index < 0 or not 1 <= items_per_page <= 100:
            raise ValueError("start_index must be nonnegative; items_per_page must be 1–100")
        return {"start_index": start_index, "items_per_page": items_per_page}

    def search(self, query, *, start_index=0, items_per_page=100) -> SearchResults:
        if not query.strip():
            raise ValueError("search query cannot be blank")
        return self._get("/search/companies", {"q": query.strip(), **self._page(start_index, items_per_page)}, SearchResults)

    def profile(self, company_number) -> CompanyProfile:
        return self._get(f"/company/{self._company_number(company_number)}", {}, CompanyProfile)

    def filings(self, company_number, *, start_index=0, items_per_page=100) -> FilingHistory:
        return self._get(f"/company/{self._company_number(company_number)}/filing-history",
                         self._page(start_index, items_per_page), FilingHistory)

    def _retry_delay(self, response, attempt):
        header = response.headers.get("Retry-After")
        # RFC 9110 permits an HTTP date or nonnegative integer seconds.
        # Reject numeric extensions (negative, fractional, NaN, infinity) rather
        # than turning an invalid rate-limit response into an immediate retry.
        fallback = 300 if response.status_code == 429 else 2 ** attempt
        if not header:
            return fallback
        header = header.strip()
        if re.fullmatch(r"[0-9]+", header):
            try:
                delay = float(header)
            except (ValueError, OverflowError):
                return fallback
            return delay if math.isfinite(delay) else fallback
        try:
            when = parsedate_to_datetime(header)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            delay = when.timestamp() - self.clock()
        except (ValueError, TypeError, OverflowError):
            return fallback
        return max(0, delay) if math.isfinite(delay) else fallback

    def _get(self, endpoint, params, model):
        digest = hashlib.sha256(json.dumps([endpoint, params], sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / f"{digest}.json"
        if self.cache_ttl:
            try:
                cached = json.loads(path.read_text())
                age = self.clock() - cached["fetched_at"]
                if 0 <= age < self.cache_ttl:
                    return model.model_validate(cached["data"])
            except (OSError, ValueError, KeyError, TypeError):
                pass  # Corrupt/expired cache is a miss, never a source of transaction truth.
        for attempt in range(self.max_attempts):
            try:
                response = self.client.get(endpoint, params=params)
            except httpx.TransportError as exc:
                if attempt + 1 == self.max_attempts:
                    raise CompaniesHouseError("Companies House request failed after bounded retries.") from exc
                delay = 2 ** attempt
                if delay > self.max_retry_wait:
                    raise CompaniesHouseError("Network retry wait exceeds configured limit.") from exc
                self.sleep(delay)
                continue
            if response.status_code == 429 or response.status_code in (500, 502, 503, 504):
                delay = self._retry_delay(response, attempt)
                if attempt + 1 == self.max_attempts or delay > self.max_retry_wait:
                    raise CompaniesHouseError(f"Companies House HTTP {response.status_code}; retry after at least {delay:g} seconds. No early retry attempted.")
                self.sleep(delay)
                continue
            if response.status_code != 200:
                raise CompaniesHouseError(f"Companies House HTTP {response.status_code}; request not retried.")
            try:
                result = model.model_validate(response.json())
            except (ValueError, ValidationError) as exc:
                raise CompaniesHouseError("Companies House returned an invalid JSON response shape.") from exc
            if self.cache_ttl:
                temporary = None
                try:
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(mode="w", dir=self.cache_dir, delete=False) as handle:
                        temporary = Path(handle.name)
                        json.dump({"fetched_at": self.clock(), "data": response.json()}, handle)
                    temporary.replace(path)
                except OSError:
                    if temporary is not None:
                        try:
                            temporary.unlink(missing_ok=True)
                        except OSError:
                            pass  # Optional cleanup must not discard a valid API response.
                    # Cache is optional; a successful validated API read remains usable.
            return result
        raise CompaniesHouseError("Companies House request exhausted retries.")
