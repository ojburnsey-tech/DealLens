# Portfolio analytics and manually selected precedents

The reusable services are `deallens.analytics` and `deallens.precedents`. They render no UI and use the finance/research services for all transaction calculations.

Only records declared VERIFIED and accepted by QA enter portfolio statistics. This is an in-memory eligibility check, not independent authentication of a human verification event. Public release loading must additionally enforce the stored verification audit trail. The current real research inventory contains one DRAFT and zero VERIFIED transactions; no actual portfolio finding can yet be claimed.

`portfolio_summary(records)` returns deal count, disclosed EV totals, median valuation and premium cohorts, cash-deal share, cross-border share, completion rate and completion days. `metric_summary(records, metric, group_by=...)` supports sector, subsector, country, buyer type, consideration, cross-border classification, status and announcement year. Synergy and leverage observations use their existing service outputs. `category_counts` and `data_quality_summary` expose counts and availability.

Every statistic retains sample size. Missing values are unavailable, not zero. Share denominators use known classifications and report missing counts. Completion rate divides completed deals by all eligible deals, including pending transactions; completion days uses completed transactions with both dates. Cash consideration share means the fraction of deals classified entirely cash, not the cash fraction of aggregate acquisition value.

Cohorts separate currency, FY/LTM, participating numerical definitions and classifications, selected EV basis, illustrative status and premium reference basis/offer stage. Definition text is deliberately conservative: differently worded definitions remain separate until an analyst provides supported consistent definitions. There is no inferred FX conversion or silent normalization. Quartiles use linear interpolation at `(n-1)*p`; calculations retain Decimal precision. Non-meaningful and materially qualified multiples are excluded. Individual observations retain their Fact/Result provenance. Profile classifications require evidence assigned to each populated field via `profile.field_evidence`.

`Screen(...)` and `screen(records, filters)` return candidates using explicit filters, never automatic comparable selections. Transaction-size filters use reported EV in an explicit currency. `selected_statistics(records, selected_ids, selection_notes=...)` requires an analyst-selected unique set and records the rationale. `implied_valuation` accepts an explicitly selected multiple, a subject FY/LTM financial Fact, the selected deal IDs, rationale and explicit EV adjustments. It retains the illustrative EV and inverse EV-to-equity bridge, including negative net debt, and propagates input qualifications and warnings.

## Notebooks

Install with `python -m pip install -e '.[dev,notebooks]'`. The six numbered notebooks in `notebooks/` call reusable services; finance formulas are not duplicated in cells. Run `python scripts/check_notebooks.py` to execute them through Jupyter without changing committed outputs. CI runs this command.

In a host that prohibits all kernel sockets, `python scripts/check_notebooks.py --in-process` executes and validates every code cell in a fresh IPython namespace per notebook. This checks cell execution but does not certify the Jupyter transport. On 9 September 2026, all six passed this mode; both TCP and IPC kernel startup were blocked by the execution host. Empty verified populations show n=0 and no invented chart. Charts with observations label metric, units, sample size and basis. No causal or owner-authored conclusions are generated.
