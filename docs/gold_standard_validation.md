# DL-00001 source reconciliation — provisional

**This is not yet a VERIFIED gold-standard case.** No manually reviewed expected results were supplied by the owner. The tests use independently transcribed source arithmetic and preserve DRAFT status. Final acceptance of steps 21–22 requires the full scheme document and the owner's review of `research/inbox/DL-00001_REVIEW.md`.

`tests/test_gold_standard.py` runs without network access or a live database. It imports the checked-in YAML into temporary DuckDB, checks nested provenance, rollback on duplicate import, all available calculations, and the CLI validation/import/QA/evidence workflow. It never changes the real deal to VERIFIED.

## Independent expectations

Inputs, source publication dates, pages, definitions and ambiguities are listed in the [review sheet](../research/inbox/DL-00001_REVIEW.md). The following expectations come from explicit arithmetic on those inputs, not snapshots of production output.

| Calculation | Independent expression | Expected result |
|---|---|---:|
| Fully diluted shares | 248,906,262 + 6,028,506 + 351,897 − 1,693,930 − 1,785,000 | 251,807,735 |
| Equity | 13.15 × 251,807,735 | GBP 3,311,271,715.25 |
| EV, reported equity basis | (3,311 + 694 + 70 + 5.5 + 23.9) × 1m | GBP 4,104,400,000 |
| LTM revenue | 1,748.6 + 880.3 − 794.0 | GBP 1,834.9m |
| LTM adjusted EBITDA | 287.6 + 132.4 − 117.5 | GBP 302.5m |
| LTM adjusted EBIT | 218.4 + 100.4 − 85.3 | GBP 233.5m |
| LTM adjusted earnings | 156.7 + 67.0 − 58.9 | GBP 164.8m |
| EV / revenue | 4,104 / 1,834.9 | 2.23663415x |
| EV / reported rounded EBITDA | 4,104 / 303 | 13.54455446x |
| EV / reconstructed EBITDA | 4,104 / 302.5 | 13.56694215x |
| EV / adjusted EBIT | 4,104 / 233.5 | 17.57601713x |
| Equity / reported adjusted earnings | 3,311 / 165 | 20.06666667x |
| Close premium | 1,315 / 970 − 1 | 35.56701031% |
| Three-month VWAP premium | 1,315 / 897 − 1 | 46.59977703% |
| Shareholder consideration | 12.90 acquisition cash + 0.25 special dividend | GBP 13.15/share |
| Illustrative cost synergy / EV | 100 / 4,104 | 2.43664717% |
| Illustrative cost synergy / EBITDA | 100 / 303 | 33.00330033% |
| Illustrative synergy-adjusted multiple | 4,104 / (303 + 100) | 10.18362283x |

Display rounding above does not enter assertions. Repeating results use Decimal division in the tests.

## Differences investigated

1. **Equity:** the source's GBP 3,311m is rounded. Exact disclosed shares × dividend-inclusive value gives GBP 3,311.27171525m. Both survive independently.
2. **EV:** summing the source's displayed components gives GBP 4,104.4m versus reported GBP 4,104m. The GBP 0.4m reconciliation remains visible. The bridge deliberately starts with reported equity. Starting with exact calculated equity would give GBP 4,104.67171525m; it would be a different explicit basis, not a correction to reported EV.
3. **EBITDA:** rounded announcement LTM 303 differs from reconstructed 302.5. Reported 13.6x cannot be reproduced to one decimal from displayed 4,104 / 303 (13.5x). The more precise statement-derived denominator gives 13.5669x, consistent with 13.6x. This is an inference from disclosed inputs, not evidence of the issuer's undisclosed exact model. QA flags the LTM difference; tests retain both expectations.
4. **Earnings:** reported adjusted earnings 165 versus reconstruction 164.8 also produces an explicit reconciliation flag. These are adjusted earnings, not statutory profit.
5. **Leases:** the acquisition EBITDA definition precedes rental-charge deductions; net debt excludes leases, which are added explicitly in EV. Using covenant EBITDA 276.7 or adding leases twice would change the economics.
6. **Dividend:** 1,315p measures shareholder receipts; 1,290p is buyer acquisition cash. The target dividend is not automatically inserted into buyer debt funding.

## Deliberately unavailable calculations

No complete comparable buyer EBITDA/net-debt/funding inputs were established. Leverage tests for this record verify that the output is withheld; they do not fabricate a real-deal leverage ratio. Synthetic tests separately cover all step 16 scenarios. The same applies to simplified EPS. No revenue synergy margin is supplied, so there is no revenue-to-EBITDA contribution. All cost-synergy adjusted ratios are illustrative.

## Final human gate

Retrieve and review the full scheme document; resolve the review sheet; provide independently checked expected results and reviewer notes. Run validation, import, QA and evidence audit. After explicit verification and export, add the verified research version and reviewer-approved expectations in a follow-up commit. If expectations differ materially, investigate source definitions, dates, units and bridges; do not simply replace test expectations with production output. Until then this file and the fixture must retain their provisional labels.
