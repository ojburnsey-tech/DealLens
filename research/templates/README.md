# Human research workflow

```text
Primary documents → research YAML → validation → manual review → import → calculations → QA → reports
```

Run `deallens deal template --output research/inbox/DL-00002.yml`.
Fill in the identity and all established observations. The generated template is a valid DRAFT with unknown financial data.
It deliberately contains no invented numbers or automatic unaffected date.
Use `null` for unknowns and explicit evidence-supported zeroes for established zeroes.

```bash
deallens deal validate research/inbox/DL-00002.yml
deallens deal import research/inbox/DL-00002.yml
deallens deal show DL-00002
deallens deal calculate DL-00002
deallens qa deal DL-00002
deallens evidence audit DL-00002
```

Set `DEALLENS_DB` or put `--db /path/to/deallens.duckdb` before the command.
Imports reject duplicate deal IDs; they never overwrite an existing record.
All rows for a deal, sources, evidence and financial observations commit together or roll back together.
Validation does not require opening the database.

## Observation shape

```yaml
value: '1290'
unit: currency/share
currency: GBP
scale: '0.01'
definition: Cash acquisition price per target share, excluding special dividend
period: null
as_of: '2024-07-08'
evidence: [E-PRICE]
classification: REPORTED
ambiguity: null
```

Allowed units are `currency`, `currency/share`, `shares`, `fraction`, `ratio`, `months`.
Use annual income-statement flows with a period:

```yaml
period:
  start: '2023-01-01'
  end: '2023-12-31'
  basis: FY
```

Period bases: `FY`, `YTD`, `LTM`, `FORECAST`, `RUN_RATE`.
FY and LTM remain distinct; a selected metric is explicitly supplied under `target_financials.<metric>.selected`.
Each series can separately hold `latest_fy`, `current_ytd`, `prior_ytd` and `selected`.
Cash and debt use `as_of` with `period: null`.
`classification` is `REPORTED`, `CALCULATED` or `ASSUMPTION`.
Any calculated input must document its source inputs and derivation in evidence.

## Sources and evidence

```yaml
sources:
  - source_id: S-ANNOUNCEMENT
    title: Firm-intention announcement
    url: https://issuer.example/announcement
    publication_date: '2024-07-08'
    source_type: ANNOUNCEMENT
field_evidence:
  - evidence_id: E-PRICE
    source_id: S-ANNOUNCEMENT
    section: Section 2, terms of the acquisition
    reported_unit: pence per ordinary share
    note: Cash price excludes a separately disclosed distribution.
```

Every populated material numerical field should have evidence. Evidence records link to a source with publication date and URL and retain section/page and the reported unit.
Missing evidence blocks publication but does not prevent saving a DRAFT for further work.
Unknown evidence/source references and duplicate YAML keys are validation errors.

## Offers and premium references

`offer_terms` is a list of `{offer_id, stage, date, price, basis}`; stage is `initial`, `revised` or `final`.
`selected_offer_id` chooses one explicitly for default calculations.
`unaffected_price` is a list of `{reference_id, price, reference_date, reference_basis, selection_notes}`.
Reference basis is `unaffected_close`, `1M_VWAP` or `3M_VWAP`.
Selection notes must explain why the reference predates material takeover information.

## Equity and EV inputs

`transaction_valuation` separately holds reported equity, enterprise and transaction values.
`share_components` contains `{component_id, kind, shares, method, exercise_price, basis}`.
Kinds: `ordinary`, `options`, `restricted_stock`, `employee_awards`, `convertibles`.
Methods: `gross` for ordinary/restricted/awards, `treasury_stock` for options (exercise price required), `if_converted` for convertibles.
`share_basis` explains non-overlap and completeness.

`equity_for_ev` is an explicit observation used to build EV.
`ev_adjustments` contains `{adjustment_id, kind, amount, sign, basis}`.
Kinds: `net_debt`, `preferred_stock`, `minority_interest`, `non_operating_investments`, `other`.
Sign is `1` except non-operating investments (`-1`); other adjustments explicitly choose either sign.
Negative net debt is allowed. Nonzero balance-sheet adjustments require `as_of` dates. `ev_bridge_basis` explains the included and excluded components. If snapshot dates differ, `snapshot_alignment_basis` must explain the comparison; the resulting qualification prevents unqualified publication.
`preferred_ev_basis` is `reported` or `calculated`; no hidden fallback occurs.

## Other models

`consideration` supplies `cash`, `exchange_ratio`, `bidder_price`, `bidder_reference_date`, `other`, `structure`, `reference_basis`.

`synergies` contains `{synergy_id, kind, amount, eligible, realisation_months, revenue_margin, basis}`.
Kinds: `cost`, `revenue`, `capex`, `financial`, `implementation_cost`.
Eligible recurring cost/revenue synergies need an annual `RUN_RATE` period; a revenue margin is an explicit fraction.

`leverage_inputs` supplies `buyer_net_debt`, `target_net_debt`, `cash_consideration`, `fees`, `new_equity_proceeds`, `disposal_proceeds`, `buyer_ebitda`, `target_ebitda`, `eligible_cost_synergy`, `adjustments`, `basis`.

`accretion_inputs` supplies `buyer_net_income`, `buyer_diluted_shares`, `target_net_income`, `eligible_pretax_synergies`, `tax_rate`, `new_debt`, `incremental_interest_rate`, `new_shares_issued`, `recurring_adjustments`, `basis`.
Recurring adjustments are **signed after-tax** amounts, not pre-tax costs.
Both adjustment lists use `{adjustment_id, amount, basis}`. Nonzero eligible synergies require annual run-rate periods or explicit annual assumptions, and recurring earnings adjustments require compatible annual periods. Leverage inputs optionally accept `snapshot_alignment_basis` for explicitly qualified date mismatches.
Use an explicit empty list when no adjustments apply; use null-valued facts when a component is unknown.

## Human review status

`DRAFT` is unreviewed. `REVIEWED` requires a named reviewer and review date.
`VERIFIED` is a distinct state requiring manual verification notes.
An import never grants `VERIFIED`; direct VERIFIED imports are rejected.
Do not edit a review field to imply another person reviewed something.
`research/verified/` is reserved for records that actually pass the human verification workflow.

## Complete a real manual verification

After checking the original documents and independently reviewing every important calculation, write your actual findings to a notes file, then run:

```bash
deallens deal verify DL-00001 --reviewer 'Your name' --notes-file path/to/actual-review.md --confirm-manual-review
```

The command rejects missing evidence, schema/calculation errors and material qualifications.
Any remaining REVIEW codes must be acknowledged individually using repeated `--acknowledge-review CODE` arguments, with the reasons recorded in your notes.
It stores the reviewer, time, notes, acknowledged codes and SHA-256 of the reviewed document in the same transaction as the VERIFIED transition.
This is an explicit attestation by the person running the command; it does not independently prove that they read the source documents.

Export after successful verification:

```bash
deallens deal export DL-00001 --output research/verified/DL-00001.yml
```

Export refuses to overwrite an existing file. Imports still refuse VERIFIED records and never overwrite existing deal IDs.
