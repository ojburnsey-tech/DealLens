# Independent public-export review

Scope: initial implementation of `src/deallens/releases.py` and the new verification-document hash in `store.py`, 9 September 2026. This review covers the reusable exporter, not readiness of the full project or its real dataset. No production code was modified. Findings below describe the reviewed implementation; retain them when recording fixes and regression results.

## HIGH — R1: public export can disclose local paths and signed access URLs

**File/functions:** `releases.py`, `safe_text`, `public_url`, `_public_record`.

The local-path denylist recognises only a few Unix directories. Both `/mnt/private/source.pdf` and `/var/data/research.pdf` pass `safe_text`. Such strings can occur in evidence notes, ambiguities and financial definitions, which are exported. The query-key check misses Azure SAS `sig`, along with common `auth` and `key` parameters. The public URL `https://example.blob.core.windows.net/source.pdf?sv=2025&sig=THIS_IS_A_SECRET_SIGNATURE` is accepted. A signed URL is a bearer credential even when its host is public.

**Failing example:** execute `safe_text('/mnt/private/source.pdf')` and `public_url('https://example.blob.core.windows.net/source.pdf?sv=2025&sig=THIS_IS_A_SECRET_SIGNATURE')`; both return normally. Reproduced against the implementation.

**Correct behaviour:** reject private path strings and credential-bearing source URLs before producing a public artifact. Traverse individual public string values before JSON escaping. Recognise common signed/authentication query keys, case insensitively; document the limits of pattern-based scanning. Do not silently strip a credential and pretend the remaining URL remains a valid source.

**Regression tests:** parameterise absolute paths in evidence notes and nested derivation text; test signed Azure and AWS URLs, credential query keys and benign public document query parameters. Assert no destination is created on failure.

## HIGH — R2: audit reports success when the manifest itself contains a secret

**File/function:** `releases.py`, `audit_release`.

Only the files listed under `manifest['files']` are passed to `safe_text`; the manifest is not scanned or strictly validated. An extra manifest property `"private": "api_key=FAKE_TEST_SECRET"` is accepted without modifying any artifact hashes. This fails the public-release security gate even though checksums still match.

**Failing example:** create a checksummed release, add the property above to `manifest.json`, then run `audit_release`. It returns `valid: True`. Independently reproduced using a temporary CSV/Parquet release.

**Correct behaviour:** require an exact manifest schema, validate its scalar values and scan its text. An integrity audit must reject detectable secrets in every allowed artifact, including the manifest. This is distinct from proving authenticity: hashes alone are correctly documented as not proving human review.

**Regression tests:** inject a secret/local path into an extra manifest property and into version metadata. Require rejection even though all six content hashes match.

## HIGH — R3: flattened valuation amounts do not carry their own currencies

**File/function:** `releases.py`, `build_release`, `COLUMNS`.

The flat CSV/Parquet row publishes `reported_equity_value` and `reported_enterprise_value`, while its only currency column comes from the offer price. Mixed-currency facts are deliberately allowed, but their individual currencies are available only inside nested JSON. A GBP offer with a USD reported EV exports `currency=GBP, reported_enterprise_value=1000000000`, creating an easily misread financial observation. The dictionary qualification helps but does not make the flat data self-describing.

**Failing example:** an attested record with a GBP offer and a USD reported EV, without incompatible financial denominators, reaches `money(fact)` which discards the valuation currency and returns only its base-unit amount.

**Correct behaviour:** rename the offer currency column explicitly and provide separate reported-equity and reported-EV currency columns alongside their amounts. Preserve explicit units and base-unit normalisation. Never imply FX conversion.

**Regression tests:** export an allowed GBP-offer/USD-EV record and assert both currencies survive in flat columns, the EV amount remains USD and no FX conversion occurs. Cover a non-unit scale and missing values.

## MEDIUM — R4: company export and nested public schema are not audited

**File/function:** `releases.py`, `audit_release`.

The audit hashes `companies.csv` but does not validate its columns, count or relationship to the verified records. A checksummed file containing only `deal_id,name` and a row for `DL-DRAFT` passes. The nested public JSON also needs only a matching ID/status and a nonempty source URL list; mandatory deal identity and source publication metadata can be removed while retaining a successful audit.

**Failing example:** a temporary release with a company row `DL-DRAFT,Unverified company`, and nested JSON containing only identity ID, VERIFIED status and a URL-only source, returned `valid: True`. The reproduction updated artifact checksums, as a normal regeneration could do; this is a semantic validation gap, not a claim that unsigned hashes prevent malicious forgery.

**Correct behaviour:** enforce the exact public record schema, source metadata, company schema, exactly one bidder and target row per exported deal, and field-by-field parity with the public records. Validate flat columns against the nested authoritative fields. Checksums establish consistency of bytes, not correctness of content.

**Regression tests:** wrong company headers; duplicate/missing roles; unrelated IDs; changed names; missing publication date; flat/nested valuation disagreement; draft/unverified company leakage.

## LOW — R5: existing verified records need an explicit migration path

**File/function:** `store.py`, `Store.__init__`; `releases.py`, `build_release`.

Existing verification events receive a null `verified_document_sha256`. Export correctly rejects them, but `Store.verify` refuses records already VERIFIED. Such databases cannot obtain a new attestation through the existing command. This does not affect the current zero-VERIFIED research dataset.

**Correct behaviour:** document that historical verification records are ineligible until an explicit supported re-attestation/migration action binds the document hash. Never backfill from the current document and imply historical review. Use explicit SQL insert column names to make future schema evolution less fragile.

## Positive observations and limits

The builder binds the verified document hash to the recorded manual verification event, re-runs QA, filters DRAFT/REVIEWED records, stages files before publishing, rejects existing destination directories and retains lossless decimal amounts and nested evidence. Hash and document updates occur in the same verification transaction. Snapshot reads and deterministic ordering support reproducibility within the pinned DuckDB version. No source documents are copied into the release. No defect was found in the basic verified-document hash update itself.

Review outcome for this initial implementation: **3 HIGH, 1 MEDIUM, 1 LOW**. Closure requires production fixes and concrete regression evidence; the current real dataset remains unverified and cannot produce a legitimate public release yet.
