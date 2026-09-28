# QA and publication policy

QA has four severities:

| Severity | Meaning |
|---|---|
| INFO | Context or successful check; not an error |
| REVIEW | A researcher should investigate or explain the observation |
| ERROR | A schema/calculation inconsistency prevents reliable use |
| BLOCK_PUBLISH | A required evidence or manual-review condition is unmet |

Reasonableness thresholds are review flags, **not assertions that a deal or source is wrong**.
The initial thresholds are premium above 200%, premium below -20%, EV/EBITDA above 50x, EV/Revenue above 30x, and eligible cost synergies above target EBITDA.
Completion before announcement is a chronological inconsistency requiring correction or a changed interpretation of the dates.
Reported versus calculated EV is reconciled rather than overwritten; a large difference needs an explanation of valuation basis, date and adjustments.

Publication requires source evidence for material numbers, a complete core deal identity and offer, no schema/calculation errors or unresolved material qualifications, and actual manual verification.
A syntactically valid DRAFT is allowed into the research database while those conditions remain unmet.
An ordinary import cannot perform the manual verification transition.

Expected outcomes for draft research:

- `deal validate` can succeed with explicitly unknown financial values.
- `deal import` can succeed while QA reports missing evidence or review requirements.
- `qa deal` can produce REVIEW and BLOCK_PUBLISH findings without implying that source figures are false.
- `evidence audit` checks populated material observations and their source records; it does not certify that a human opened and verified the source documents.

Snapshot-date qualifications must survive downstream calculations and prevent an unqualified publication claim.
Reported and reconstructed financial metrics can differ for valid reasons. QA should expose the difference, not silently replace the selected source measure.
