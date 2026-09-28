# Steps 8–22 acceptance checklist

This file distinguishes implemented code from the owner's required manual research sign-off.
Passing software tests does not certify a real transaction as manually verified.

| Step | Acceptance criteria | Evidence / final status |
|---|---|---|
| 8 | Structured YAML identity, bidder, target, offer terms, valuation, unaffected price, financials, synergies, financing, rationale, risks, sources, evidence and notes; template/validate/import/show; atomic import; DRAFT/REVIEWED/VERIFIED distinction; research directories; malformed/duplicate/missing/success tests | `research.py`, `store.py`, `cli.py`, `tests/test_research.py`; import never grants VERIFIED |
| 9 | Revenue/EBITDA/EBIT/net-income LTM; no snapshot reconstruction; period length/definitions; result/inputs/formula/basis/warnings; H1/9M/missing/mismatch/negative tests; commit | `finance.ltm`, `tests/test_finance.py`; baseline commit `8a6697d` |
| 10 | Offer price × fully diluted shares; reported/calculated separate; ordinary/options/restricted/employee/convertible bridge; extensive tests | `finance.equity_value`, `ShareComponent`, finance tests |
| 11 | Explicit EV adjustments; reported/calculated/preferred values and basis; net cash; separate transaction value; reconciliation and tests | `finance.enterprise_value`, `EVAdjustment`, `research.Valuation` |
| 12 | Four multiples; numerator/denominator/period/basis/warnings; zero/negative earnings non-meaningful; FY/LTM distinction; tests | `finance.multiple` and finance tests |
| 13 | Premium formula; unaffected close/1M/3M VWAP; initial/revised/final offers; mandatory reference/date/basis/offer; no automatic date selection; requested edge tests | `finance.premium`, `Offer`, `ReferencePrice`, finance tests |
| 14 | Cash/shares/mixed/other fixed consideration; exchange ratio and bidder price/date retained; floating/collared safeguards; tests | `finance.consideration`, finance tests |
| 15 | Five synergy/cost categories; realisation timing; cost/EV and cost/EBITDA; illustrative adjusted multiple; explicit revenue margin only; tests | `finance.synergy_analysis`, `Synergy`, finance tests |
| 16 | Standalone, PF net debt, EBITDA before/after synergy and leverage; all financing components; cash/mixed/net cash/new equity/missing tests | `finance.leverage`, finance tests |
| 17 | Simplified EPS model; all requested inputs/outputs; full bridge; clear PPA exclusion; extensive tests | `finance.accretion`, finance tests |
| 18 | Separate reviewer worktree; adversarial report with severity and reproductions; another task fixes every actual critical/high defect; regression tests; complete suite; independent recheck | Complete: `REVIEW_FINANCE_ENGINE.md`; separate reviewer and fixer tasks, 99 regression cases, independent re-review confirms CRITICAL=0/HIGH=0 |
| 19 | INFO/REVIEW/ERROR/BLOCK_PUBLISH; all requested thresholds; schema/provenance/reconciliation/publishability; qa deal/all/report; tests | Complete: `qa.py`, `store.verify`, `tests/test_qa.py`; CLI tested end to end |
| 20 | Environment-only Companies House key; search/profile/filings; timeouts/retries/rate limits/typed models/cache; mocked tests; no transaction overwrites | Complete: `companies_house.py`, `tests/test_companies_house.py`; all HTTP mocked |
| 21 | ONE primary-source UK takeover; DL-00001 YAML and review sheet; material numbers tied to date/section/unit/classification/ambiguity; nulls for unknowns; validate/import/QA/audit; human review retained | Prepared: `research/inbox/DL-00001.yml` and `DL-00001_REVIEW.md`; validation/import/QA/audit executed in integration tests. NOT fully complete: full scheme retrieval and owner manual verification remain |
| 22 | Real-deal import/provenance/equity/EV/LTM/multiple/premium/synergy/leverage tests where available; independent expected calculations and reconciliation document | 19 passing provisional real-case tests in `tests/test_gold_standard.py`; reconciliation in `docs/gold_standard_validation.md`. NOT fully complete: no owner-verified expected results yet; unavailable leverage inputs remain null |

## Human-only gate

The user explicitly requires a manual check of offer price, share count, equity value, enterprise value, target debt, target cash, revenue, EBITDA, period, unaffected price, premium, synergies, financing and status before verification.
The assistant can prepare and test the full research package, but cannot claim that the owner's review has occurred.
Until the owner signs off, DL-00001 and any integration expected values remain **provisional, unverified**.

## Final software validation

`python -m ruff check .` passes. `python -m pytest -q` passes **303 tests**, including all 19 real-case integration tests. GitHub Actions runs the same lint and test gates on pushes and pull requests. No real deal was marked VERIFIED.

Steps 8–20 are implemented and tested. Steps 21–22 are prepared and tested as a DRAFT case, with the missing source and human sign-off explicitly outstanding. This distinction is intentional; it is not a claim that every human-dependent step is finished.
