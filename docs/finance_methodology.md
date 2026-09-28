# Finance engine methodology

All results use Python `Decimal`. No display rounding is applied inside calculations.
`Fact.value` preserves the reported figure and `Fact.scale` converts it to base units.
For example, 1,290 pence is value `1290`, scale `0.01`, unit `currency/share`, currency `GBP`.
£100 million is value `100`, scale `1000000`, unit `currency`, currency `GBP`.
Two million shares are value `2`, scale `1000000`, unit `shares`.
A 25% tax rate is value `0.25`, unit `fraction`, scale `1`.
There is no automatic foreign-exchange conversion. Supply a separately sourced conversion with the rate and date in its evidence.

## Missing data and calculation lineage

`null` means unknown. An explicit zero means the researcher has established zero.
Neither imports nor calculations turn a missing input into zero.
An empty bridge list means the researcher explicitly included no adjustments; its accompanying basis must explain scope.
Every `Result` retains its inputs, formula, basis, warnings, material qualifications, output unit and applicable financial period. A calculated `Fact` reused downstream embeds its original `Result` as `derivation`, so its exact bridge survives export.
The input observations preserve evidence identifiers, reported/calculated/assumption classification and ambiguity notes.
The CLI emits decimal values as JSON strings to avoid float precision loss.

## LTM

`Latest FY + Current YTD - Prior-year comparable YTD` applies to revenue, EBITDA, EBIT and net income.
Cash, debt and net debt are dated balance-sheet snapshots and cannot be reconstructed this way.
The year and YTD dates, financial definitions, currencies and comparable lengths must agree.
Current YTD begins immediately after FY. Prior YTD begins with FY.
52/53-week and leap-year differences must be considered rather than blindly matching labels such as H1.

## Equity value

`Offer price × fully diluted shares` is retained separately from reported equity value.
Ordinary shares, restricted stock and employee awards enter as explicitly separate gross counts.
Options use incremental treasury-stock shares: `options × max(0, 1 - strike / offer price)`.
Convertibles use researcher-supplied if-converted share counts. The corresponding converted liability must be removed from debt in the EV bridge.
Shares already included in another share count must not be supplied again.
The offer-price basis must explain dividends, distributions and any difference from headline shareholder value.

## Enterprise value

`Equity value + net debt + preferred stock + minority interest - non-operating investments` is a framework.
Only explicitly supplied adjustments are applied. Signed other adjustments require a stated basis.
Negative net debt represents net cash and is allowed. Known nonzero balance-sheet adjustments require snapshot dates and cannot use flow periods. Differing dates require `snapshot_alignment_basis`; the resulting material qualification remains visible and blocks unqualified publication.
Reported enterprise value, calculated enterprise value and the selected preferred basis remain separate.
A selected missing reported EV does not silently fall back to calculated EV.
Reconciliation is `calculated - reported`; relative difference divides this by the absolute reported EV.
Relative reconciliation is unavailable for reported EV of zero.
Reported transaction value has its own field and is never substituted for equity or EV.

## Multiples and premiums

EV/Revenue, EV/EBITDA, EV/EBIT and Equity Value/Net Income retain the selected FY or LTM denominator.
Zero or negative earnings denominators do not produce an ordinary acquisition multiple.
A negative valuation numerator is also flagged as analytically non-meaningful.

Premium is `Offer price / Reference price - 1`. Rates are fractions, not percentage points.
Each reference requires its price, date and basis; references can be unaffected close, 1M VWAP or 3M VWAP.
The researcher chooses the unaffected date from the transaction history. The code never selects it.
Initial, revised and final offers have separate identities; an explicit selected offer determines the default analysis.

## Consideration

`Cash + exchange ratio × bidder reference share price + eligible other consideration` gives value per target share.
A cash-only transaction explicitly sets the exchange ratio and other measurable consideration to zero.
Share consideration requires a bidder reference date and explanation.
Floating and collared structures produce only an explicitly labelled reference scenario when a basis is supplied.
The researcher must supply the exchange ratio applicable to that scenario; the engine does not solve collar terms.

## Synergies

Cost, revenue, capex and financial synergies and implementation costs remain distinct.
Only eligible annual cost savings enter the standard synergy-adjusted EBITDA multiple.
Revenue synergies are not EBITDA. An explicit margin allows a separate illustrative EBITDA conversion, without silently adding it to the cost-synergy multiple.
One-off implementation costs do not enter recurring EBITDA. Their amount and realisation periods remain visible.
All synergy-adjusted calculations are illustrative annual run-rate scenarios, not realised earnings or forecasts.

## Acquisition leverage

`Buyer net debt + target net debt + cash consideration + fees - new equity proceeds - disposal proceeds + signed adjustments`.
Cash funding increases net debt whether cash comes from existing cash or new borrowing.
Do not also add acquisition borrowing to this bridge; that double counts the same funding need.
Buyer and target earnings require matching periods, bases and accounting definitions.
Known nonzero buyer and target net debt require snapshot dates. Different dates require `snapshot_alignment_basis` and produce a material qualification. Eligible nonzero synergies require an annual run-rate or explicitly annual assumption. The bridge preserves every funding component. Net cash may legitimately produce negative leverage.
Non-positive aggregate EBITDA does not produce an ordinary leverage ratio.

## Simplified accretion/dilution

The model uses full-year income and full-year incremental financing/share issuance.
Buyer diluted shares are the weighted-average denominator corresponding to buyer standalone EPS.
Incremental interest is `new debt × annual interest rate`.
After-tax interest and eligible synergies use `pre-tax amount × (1 - tax rate)`.
Pro-forma net income is buyer NI plus target NI minus after-tax interest plus after-tax synergies **plus signed after-tax recurring adjustments**.
A recurring expense therefore enters as a negative adjustment. This signed interface is equivalent to subtracting a positive expense in the conceptual README formula.
Pro-forma diluted shares are buyer diluted shares plus new shares issued.
Accretion/dilution is `pro-forma EPS / standalone EPS - 1`; non-positive standalone EPS makes this percentage non-meaningful.

The output explicitly states that the model is simplified. Detailed purchase-price accounting, interest foregone, refinancing of target debt, amortisation, tax deductibility constraints and timing effects are excluded unless reflected in separately supplied adjustments or assumptions.
