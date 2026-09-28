# Independent Companies House review

Reviewed 8 September 2026 against commit `b1b15222d05be0dc567a6cb2a016086c455c7837`.
Scope: `companies_house.py`, CLI routing, response models, integration documentation and mocked tests. No applicable `AGENTS.md` was found. The reviewer changed only this report.

**Initial findings: CRITICAL 0; HIGH 0; MEDIUM 3; LOW 1.** Existing behavior meets the main functional requirements, but three defensive edge cases need correction before describing the client as fully hardened. These counts record the initial review; a dated closure section should retain the findings and document subsequent fixes.

## Requirement assessment

| Requirement | Result | Evidence / limitation |
|---|---|---|
| Environment-only API key | PASS | Constructor reads `COMPANIES_HOUSE_API_KEY`; no key CLI argument. Missing key fails clearly. Basic authentication is tested. |
| Company search | PASS | Typed results, query parameters and pagination supported. |
| Company profile | PASS | Typed identity response, eight-character company number validation and preserved leading zeros. |
| Filing history | PASS | Typed filing dates, descriptions, transaction IDs and pagination. |
| Three CLI commands | PASS | Search/profile/filings route to the isolated client and return before opening a database. Direct command-specific integration coverage can improve: L1. |
| Timeouts | FAIL | Safe default exists, but explicit non-finite timeout values pass validation: M3. |
| Bounded retries | PASS | Maximum attempts is bounded; transport failures and selected transient statuses retry; other statuses do not. |
| Conservative rate limiting | FAIL | Ordinary numeric and HTTP-date headers work, but negative numeric headers trigger immediate retries: M1. |
| Typed models | PASS | Required identity and filing fields are validated. Additional public API metadata is retained. Invalid shapes are rejected before caching. |
| Local caching | FAIL | Keys include endpoint and parameters; atomic writes, TTL and validation work. Cleanup failure can discard an otherwise successful API response: M2. |
| All API tests mocked | PASS | All exercised HTTP calls use `httpx.MockTransport`; tests require no live credentials. |
| No verified transaction overwrite | PASS | Client has no Store dependency or transaction mutation path. CLI completes Companies House handling before entering `Store`. |

## Findings

### M1 — MEDIUM: malformed negative Retry-After values trigger immediate retries

File/function: `src/deallens/companies_house.py`, `CompaniesHouse._retry_delay`.

`float(header)` accepts `-1` and `-inf`. Both become zero through `max(0, delay)`, allowing an immediate retry after HTTP 429. Negative numeric delay-seconds are invalid and should not be treated as permission to retry immediately. This differs from a valid HTTP-date in the past, for which an elapsed wait can legitimately be zero.

Reproduction: a mock transport returns HTTP 429 with `Retry-After: -1` (or `-inf`) once, then HTTP 200 with a valid profile; use `cache_ttl=0` and `sleep=waits.append`. Observed **two requests and `waits == [0]`**. Correct behavior: invalid numeric header follows the conservative missing/invalid-header policy, which at default settings stops with a retry-later error rather than making an early request.

Regression: parameterize negative and non-finite numeric strings; assert no second request when the conservative fallback exceeds the configured wait budget. Retain valid zero, positive integer and HTTP-date tests.

### M2 — MEDIUM: failed cache cleanup discards valid API data

File/function: `src/deallens/companies_house.py`, `CompaniesHouse._get` cache-write exception handler.

After a write or rename `OSError`, `temporary.unlink(missing_ok=True)` is unguarded. A second filesystem error during cleanup escapes and discards the successfully validated HTTP response. This contradicts the documented guarantee that optional cache failure does not discard a successful API read.

Reproduction: return a valid profile via mock transport; patch `Path.replace` to raise `PermissionError("rename denied")` and `Path.unlink` to raise `PermissionError("cleanup denied")`. Observed **`PermissionError: cleanup denied`**, instead of the typed profile. Correct behavior: best-effort cleanup must not obscure successful API data; a leftover temporary cache file can be tolerated when permissions prevent removal.

Regression: simulate both failed rename and failed cleanup, and assert the validated company profile is still returned.

### M3 — MEDIUM: non-finite configuration bypasses timeout validation

File/function: `src/deallens/companies_house.py`, `CompaniesHouse.__init__`.

The `timeout <= 0` guard accepts both NaN and positive infinity. Construction succeeds and `client.client.timeout.read` contains the non-finite value. Infinity defeats the intended finite request timeout; NaN creates invalid runtime timing behavior. `cache_ttl` similarly lacks a finiteness check, allowing a cache policy that cannot reliably expire or be compared.

Reproduction: instantiate with `timeout=float("nan")`, then separately `timeout=float("inf")`, a mock transport and environment-only mock key. Both constructions succeed. Correct behavior: reject non-finite values for timeout, cache TTL and retry wait before creating the HTTP client; validate attempts as an integer rather than allowing a later `range()` failure for a float.

Regression: parameterize NaN/infinity and invalid numeric types across configuration parameters; retain tests allowing zero cache TTL and zero retry budget where explicitly supported.

### L1 — LOW: CLI isolation is inspected but not protected by direct tests

The existing suite exercises the client rather than the actual three CLI commands. The current dispatch is correct, but tests do not directly guarantee JSON output, error exit codes and absence of database writes at this boundary.

Suggested regression: invoke `main()` for search/profile/filings with a mock client transport; make opening `Store` fail if attempted; verify success JSON and missing-key/API-error exit codes. This is a coverage improvement, not an observed production defect.

## Executed verification

- `python -m pytest tests/test_companies_house.py -q`: **24 passed**.
- `python -m ruff check src/deallens/companies_house.py tests/test_companies_house.py`: **passed**.
- Additional read-only Python reproductions confirmed M1, M2 and M3 as described above. No production files or tests were changed by this reviewer.
- Initial test execution encountered missing runtime dependencies; tests were rerun successfully after the main task restored the environment.

## Primary API references

The response fields were checked against the official [filing history schema](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/resources/filinghistorylist?v=latest). The conservative five-minute fallback is consistent with the official [rate-limiting guidance](https://developer-specs.company-information.service.gov.uk/guides/rateLimiting), which documents 600 requests per five-minute period. These references support API contract checks; no live company API requests were made.

## Implementation follow-up (root task)

M1–M3 are repaired with 30 new regression cases: malformed/non-finite retry headers use a conservative fallback; numeric configuration is finite and bounded; optional cache cleanup is best effort. Three further CLI tests address L1 and fail if metadata lookup opens the transaction database. The original findings above are retained. The updated full repository suite passes 303 tests; mypy passes. These repairs have not yet received a separate independent re-review: the follow-up agent was unavailable and the delegated hardening task reported a usage limit. This note is not a claim of independent closure.
