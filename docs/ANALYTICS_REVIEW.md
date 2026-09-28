# Independent analytics and precedents review

Reviewed 2026-09-09. Scope: `analytics.py`, `precedents.py`, the `ResearchProfile` addition, the profile QA provenance gate, and their tests. Production code was not changed. Synthetic test records only were used; DL-00001 remains DRAFT. These findings are based on implementation inspection and focused executable reproductions, not an assumption that the existing 42 tests establish correctness.

Initial findings: **HIGH 3, MEDIUM 2, LOW 1**. This is a repair list, not release approval.

## HIGH A1 — Multiple cohorts omit numerator definitions

**File/function:** `src/deallens/analytics.py`, `observations` / `metric_summary`.

The cohort basis uses the result's period and `Result.basis`. `finance.multiple` describes only the denominator in that basis. Consequently EV definitions and the chosen reported/calculated valuation basis do not contribute to the cohort key.

**Reproduced example:** the existing synthetic verified fixture has reported EV 1,000 and adjusted FY EBITDA 100. A second otherwise comparable fixture has reported EV 1,200 explicitly defined as “EV including pension deficit.” `metric_summary(..., 'ev_ebitda')` returns one cohort, n=2, median 11.0x, with basis `FY; FY; Adjusted EBITDA; illustrative=False`. The numerator distinction is invisible in the summary. The underlying observation retains it, but that does not prevent the misleading pooled statistic.

**Correct behaviour:** retain a structured comparison basis including numerator definition and the chosen EV basis, alongside denominator definition and FY/LTM. Different definitions should remain separate unless an explicit analyst normalization has established comparability. Do not use evidence IDs or issuer-specific narrative as a substitute for a meaningful normalized basis.

**Regression:** same-denominator records with different EV definitions must form different cohorts; reported and calculated EV selection must be exposed. Repeat for equity/net-income numerator definitions.

## HIGH A2 — Synergy and leverage cohorts omit earnings definitions

**File/function:** `src/deallens/analytics.py`, `observations`.

Synergy results use a generic “Illustrative annual run-rate cost synergies” basis. Leverage results use the caller's funding narrative. Neither necessarily identifies the underlying EBITDA definition. Analytics only appends FY/LTM and the illustrative marker, so equal narratives permit adjusted EBITDA and materially different accounting EBITDA to be pooled. Within-deal buyer/target comparability checks do not address comparability across deals.

**Failing example:** two FY acquisitions use target EBITDA definitions “Adjusted EBITDA excluding lease rental payments” and “EBITDA before lease rental payments”. Both synergy calculations get the same cohort basis despite different denominators. Two leverage records with different earnings definitions and the same funding narrative have the same issue.

**Correct behaviour:** derive cohort metadata from the actual participating Facts: target EBITDA for synergy metrics, buyer/target EBITDA for leverage, and valuation definition where EV participates. Preserve annual run-rate and illustrative labels. Separate differing definitions rather than relying on free-text funding notes.

**Regression:** paired records with equal period basis and generic result basis but different underlying EBITDA definitions must not share a cohort for cost_synergy_ebitda, synergy_adjusted_multiple, and leverage_before_synergy / leverage_after_synergy.

## HIGH A3 — Subject valuation loses material inherited qualifications

**File/function:** `src/deallens/precedents.py`, `implied_valuation`.

The function directly creates `Result` objects instead of applying the finance service's inherited-warning and inherited-qualification handling. It copies warnings from its own missing-value checks and the EV adjustments, but drops qualifications and warnings embedded in a derived selected multiple or subject financial.

**Reproduced example:** subject FY EBITDA 20 is a `derived_fact` whose derivation has qualification “Material accounting comparability gap” and warning “Do not use without resolving gap”. A selected multiple of 10 produces implied EV 200 with `warnings=()` and `qualifications=()`. Implied equity also has empty qualifications. The nested input preserves the original record, but a caller inspecting the output flags sees an apparently unqualified valuation.

**Correct behaviour:** propagate inherited material qualifications and warnings from both selected multiple and subject financial into implied EV and then into implied equity. Prefer the shared finance result construction policy, and retain the complete nested calculation bridge. Materially qualified results must remain ineligible for unqualified presentation.

**Regression:** separately qualified derived financial and derived selected-multiple inputs must carry their exact qualifications and warnings through both outputs; test round-trip serialization as well.

## MEDIUM A4 — Profile evidence is not attributable to individual classifications

**File/function:** `src/deallens/research.py`, `ResearchProfile`; `src/deallens/qa.py`, profile evidence gate.

A single profile-level list provides the same source association for sector, ultimate bidder country, public/private, buyer type and consideration type. One valid evidence reference satisfies the gate even when it supports only one classification. This cannot establish which document supports each classification, and the numerical evidence audit does not explain that distinction.

**Correct behaviour:** provide field-specific classification evidence or an explicit mapping whose keys are populated profile fields. Surface unresolved attribution in QA. A shared source is entirely acceptable when it actually supports all specified fields; the mapping makes that reviewable.

**Regression:** source evidence assigned only to sector must not imply evidence for an independently populated ultimate bidder country. Unknown fields remain valid and must not become domestic/cash by default.

## MEDIUM A5 — `Screen` annotations do not validate runtime inputs

**File/function:** `src/deallens/precedents.py`, `Screen.__post_init__` / `screen`.

The dataclass uses `Literal` annotations but validates only EV bounds. `Screen(financial_metric='net_debt', financial_basis='FY')` is accepted on construction and can raise AttributeError in screening; invalid buyer types or financial bases silently return no records. These are invalid requests, not honest zero-sized cohorts.

**Correct behaviour:** validate enum fields, supported financial metrics and currency syntax when constructing the screen, using a typed validation model or explicit checks. Invalid filters should raise a clear validation error before reading the dataset.

**Regression:** unsupported metric, financial basis and buyer type reject deterministically; valid filters with no matching records still return n=0.

## LOW A6 — Non-finite validation occurs after sorting

**File/function:** `src/deallens/analytics.py`, `distribution`.

The function sorts before checking `is_finite`. A lone Decimal NaN is covered, but a mixed list such as `[Decimal(1), Decimal('NaN')]` can raise Decimal InvalidOperation during ordering rather than the documented ValueError.

**Correct behaviour:** materialize and validate values before sorting. Add mixed finite/NaN and infinity cases. This does not change any valid statistic.

## Confirmed strengths and boundaries

- Unverified deals and QA-blocked deals are excluded, and duplicate IDs reject rather than inflate sample size.
- Missing/non-meaningful multiples have explicit missing counts. Empty populations remain unavailable rather than zero-valued statistics.
- Disclosed EV totals retain currency and definition; no implicit FX conversion is performed.
- Premium bases and offer stages remain separate; duplicate references within one deal and comparison basis reject.
- Cross-border status uses explicitly supplied ultimate bidder country, not a bid vehicle's domicile. Unknown classifications are excluded from known-observation share denominators and counted as missing.
- The subject EV-to-equity bridge correctly reverses the enterprise-value adjustments, including negative net debt and non-operating investments, using the established finance service.
- Candidate screens do not claim automatic comparability. Selection notes and selected IDs are retained.
- These APIs accept in-memory records with a declared VERIFIED status and review notes; they do not independently authenticate a database verification event. A future public-release loader must enforce that boundary rather than presenting this filter as proof of human review.

## Verification performed

Read the production modules and all analytics/precedents tests. Executed focused synthetic reproductions using `.venv/bin/python` for A1 and A3; both reproduced exactly as described above. No tests were weakened and no real research status was changed. Repair and full-suite verification remain the implementing agent's responsibility.

## Independent closure — 9 September 2026

A separate reviewer re-read the repairs and independently ran all 61 analytics/precedents tests. A1 now includes numerator/denominator definitions and classifications plus explicit preferred EV basis. A2 separates all four requested synergy/leverage pathways using participating financial definitions. A3 uses shared result construction, preserves inherited flags in both outputs, and passes derived-multiple JSON round-trip tests. Independent reproductions using the actual finance services also passed for A2 and A3. A4 now requires field-specific classification evidence; A5 rejects invalid enum/filter requests; A6 validates finite observations before sorting. Original findings remain above.

**Open HIGH = 0; BLOCKER = 0 within this phase.** No production code was changed by the reviewer. This closure is not approval of the unverified dataset or a full application release. Notebook cell execution and Jupyter kernel protocol execution are separate checks.
