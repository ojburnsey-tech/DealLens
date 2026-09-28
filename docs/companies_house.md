# Companies House integration

This integration reads company identity and filing metadata. It is not a source of transaction economics and cannot change research records.

```bash
export COMPANIES_HOUSE_API_KEY='your-own-key'
deallens companies-house search 'Britvic'
deallens companies-house profile 00000001
deallens companies-house filings 00000001 --start-index 0 --items-per-page 100
```

Replace the illustrative company number with the exact eight-character number from a search result; preserve leading zeroes. In PowerShell set `$env:COMPANIES_HOUSE_API_KEY` instead.
Never put a key in YAML, a CLI argument, a screenshot or version control.

- HTTP Basic authentication uses the environment key as username and an empty password.
- Every request has a timeout; transient transport/server errors have bounded retries.
- 429 responses respect Retry-After, including HTTP-date values. With no header, the client conservatively treats the wait as 300 seconds. If a wait exceeds the configured short synchronous budget, it returns a clear retry-later error rather than retrying early.
- Official rate limits currently allow 600 requests per five-minute window. The CLI is sequential and does not implement a high-throughput bulk crawler.
- Search and filings expose `start_index` and `items_per_page`; responses retain total counts. Request subsequent pages explicitly.
- Validated public responses are cached for one hour by default. Cache keys include endpoint and query parameters, never credentials. Set `DEALLENS_CACHE_DIR` to change the location.
- Empty, corrupted and expired cache entries are refetched. Cache writes are atomic; cache failure does not discard a valid API response.
- All tests use `httpx.MockTransport`, including authentication, retries, rate limiting, invalid responses, pagination and cache behavior. A live API key is unnecessary for tests.

Official references, checked 7 September 2026:

- [Public Data API reference](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference)
- [API key authentication](https://developer-specs.company-information.service.gov.uk/guides/authorisation)
- [Rate limits](https://developer-specs.company-information.service.gov.uk/guides/rateLimiting)

The client rejects non-finite timeout/cache/retry settings and non-integer attempt counts. `Retry-After` follows [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after): nonnegative integer seconds or an HTTP date. Invalid values on HTTP 429 use the conservative five-minute fallback. Optional cache write and cleanup failures do not discard a validated response. CLI regression tests also ensure metadata lookups never open the transaction database.
