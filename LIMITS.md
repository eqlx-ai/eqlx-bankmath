# Limits

Read this before relying on a number.

## What the tool is

Arithmetic on the numbers you give it. A result is not an offer, a quote, a statement of account or
legal advice, and it does not replace a bank's own system. Rates and prices are inputs; the tool
never suggests one.

## Dated tables

Levy rates (KKDF, BSMV), fee ceilings, card rate spreads and minimum payment rules are set by
decree or Board decision and change without notice. They are stored as dated entries with their
legal basis, last compared with the sources on 2026-11-10. A lookup returns the entry in force and
that date; confirm it against the official source for anything after it. Where a date is given and
it lies before the earliest entry of a table, the lookup is refused instead of guessed. Some checks
take no date (card rate ceilings without `on`, the late interest multiplier, the cash advance fee):
they use the latest entry and say which.

Not confirmed from a primary text, and therefore inputs with no default or a stated caveat: BSMV on
housing loans to borrowers who already own a dwelling; BSMV on fees; the stamp duty position of a
letter of guarantee; BSMV on a commission refunded to a commercial customer.

## What is rule and what is practice

| Product | Fixed by law or regulation | Bank practice, so an argument here |
|---|---|---|
| Instalment loans (consumer, housing) | cost rate formula, levies, early repayment, late interest ceiling | almost nothing |
| Commercial instalment loans | levies, fee ceilings, early repayment fee ceiling | interest-only periods, repricing |
| Cards | minimum payment, rate ceilings, when interest starts, no compounding | day count, rounding, order in which payments are applied, late payments |
| Retail overdraft | rate ceiling, limit rule, no fees | value dates, accrual date, counting the end day |
| Revolving, current account, spot | compounding only between merchants and not more often than quarterly, fee ceilings, levies | day basis 360 or 365, accrual dates, capitalisation |
| Letters of guarantee | taxes only | period length, started periods, minimum, refunds |

For the right-hand column the defaults are the most common convention found in public sources.
They are not "the correct" ones. If you know the bank's convention, pass it.

## Instalment loans

- Monthly instalments only. Interest is `balance x monthly rate x days / 30`.
- The annual cost rate uses a 360-day year and twelve equal months, with fees paid at drawdown.
  Insurance premiums are not included: the regulation does not say whether they belong in the rate.
  Add them as cash flows with `annual_cost_rate` if your policy includes them.
- Interest collected in advance (peşin faiz, Annex 3 of the consumer regulation) is not implemented.
- Housing loan early repayment compensation is returned as a ceiling; the base (principal repaid
  early) is yours to supply.
- A partial prepayment between due dates needs the calendar days to the next due date when the
  month is not 30 days long. It is computed for equal-instalment plans only.
- After a first period longer than 30 days the interest of that period can exceed the instalment;
  the balance then grows in the first month, as the regulation's formula implies.
- Every row is rounded to the kuruş. The longer tables in the housing finance annexes (Ek-2 to
  Ek-4) were printed from unrounded annuities, so balances there differ from this library's by a
  few kuruş; the consumer annexes and the housing Ek-1 match exactly.
- On foreign-currency loans KKDF is charged once on the principal at drawdown. That base comes from
  a secondary copy of the communiqué.

## Cards and overdrafts

- One statement cycle at a time; no carried history, no instalment purchases, no restructuring plan.
- When less than the minimum is paid, the default follows the Regulation (default interest on the
  unpaid part of the minimum). The Law's wording is available as an option. Which one a court would
  apply is not for this tool to say.
- The order in which a payment is applied (charges, cash, purchases) and the treatment of payments
  after the due date are choices, not rules found in any text.
- Overdraft default interest is not implemented: what triggers it is contractual.

## Commercial products

- No regulation prescribes a cost rate for commercial loans. The annual costs returned are stated
  as simple or compounded, on 360 or 365 days, as labelled.
- Capitalising unpaid interest more often than every three months is flagged, not prevented.
- Variable-rate plans recompute the instalment at each repricing; a contract may instead keep the
  instalment and change the term.
- FX loans are computed in their own currency; no revaluation, no exchange differences.

## Letters of guarantee

- A refund never exceeds the commission collected for the period and never takes a period below
  its minimum. When a started period is charged in full and refunds are switched on, the refund is
  the released share of that charge for the days left in the period. These are design choices.
- Stamp duty, the interest after a call, extension fees and increases of the amount are not covered.
  A called letter becomes a cash loan and is outside the module.

## Not covered at all

Letters of credit and acceptances, KGF guarantee commissions, leasing and factoring, card debt
restructuring, instalment cash advances, BDDK maturity and loan-to-value limits, deposit products.

## Data

Nothing is stored or sent. Do not put real customer data into an issue, a test or an example.
