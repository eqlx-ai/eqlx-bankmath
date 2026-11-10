# eqlx-bankmath

Deterministic arithmetic for bank products in Türkiye, exact to the kuruş. A Python library, a
command line tool and an MCP server, so that an AI agent asks for the number instead of working it
out itself.

- **Instalment loans** (consumer, housing, commercial): the repayment plan with KKDF and BSMV on
  interest, the annual cost rate the regulation defines, early repayment, partial prepayment, late
  interest, and the questions asked backwards ("what can I borrow for 5,000 a month?").
- **Daily-balance products**: retail overdraft (KMH), revolving lines and current accounts
  (rotatif, borçlu cari hesap), spot loans.
- **Credit cards**: minimum payment, rate ceilings, and the interest one statement puts on the next.
- **Bills and variable rates**: discounting of bills and cheques, plans that reprice, a compounded
  reference rate.
- **Letters of guarantee**: commission period by period, under the convention you choose.
- **Ceilings**: is a fee or a rate within the regulated maximum, and under which rule?

Same input, same output. No model inside, no network, no data leaves the machine.

## Why not let the model do the arithmetic

A consumer loan of 100,000 TL at 3.99 % a month for 24 months, disbursed on 10 November 2026 with a
500 TL allocation fee:

```bash
bankmath plan 100000 0.0399 24 --product consumer --date 2026-11-10 --fee 500
```

```text
instalment 7,379.48   last 7,379.72   total repayment 177,607.76   total cost 77,607.76
annual cost rate 84.5548 %   (monthly rate alone: 59.9186 % a year)
KKDF 15.00%   BSMV 15.00%   levies: Council of Ministers Decision 2010/974; Presidential Decision 7345 (Official Gazette 07.07.2023)
```

The rate on the poster is 59.92 % a year; what the borrower pays is 84.55 %. The difference is two
levies on interest and a fee. A language model asked for the instalment will produce a plausible
number; this produces the number, the levy rates that applied on that date, and the decree behind each.

## Install

```bash
pip install eqlx-bankmath            # library and command line; no dependencies
pip install "eqlx-bankmath[mcp]"     # with the MCP server
```

Python 3.10 or later.

## For AI agents (MCP)

```bash
claude mcp add bankmath -- bankmath mcp
```

Eighteen read-only tools; none reads or writes a file. `bankmath tools` lists them with their
arguments, and `bankmath call <tool> '<json>'` runs any of them from a terminal.

| Tool | What it returns |
|---|---|
| `loan_plan` | instalment, every row split into interest, KKDF, BSMV, principal; total cost; annual cost rate |
| `loan_early_repayment` | payoff amount and saving, or the new instalment after a partial prepayment |
| `loan_affordability` | largest loan for an instalment, shortest term, or the instalment |
| `late_payment_interest` | default interest on a late instalment, within the 1.3 x ceiling |
| `annual_cost_rate` | the regulation's rate for any set of cash flows |
| `levies` | KKDF and BSMV in force for a product on a date, with the legal basis |
| `overdraft_interest` | a period of retail overdraft use on daily balances |
| `revolving_line` | a commercial line over several accrual periods, with rate changes |
| `spot_loan` | simple interest to maturity, levies, annual cost |
| `balance_interest` | the interest-number (adat) method on any list of balances and days |
| `bill_discount` | interest taken up front, net proceeds, the rate really paid |
| `floating_rate_plan` | an instalment plan that reprices |
| `compounded_reference_rate` | an overnight rate compounded over a period |
| `card_minimum_payment` | minimum payment under the BDDK decision in force |
| `card_rate_caps` | monthly rate ceilings from the TCMB reference rate |
| `card_statement_interest` | what one statement adds to the next |
| `guarantee_commission` | commission schedule of a letter of guarantee |
| `fee_cap_check` | a quoted fee against the regulated ceiling |

## Conventions are arguments, and results say which were used

For instalment loans the regulation fixes almost everything, and its annexes print worked examples.
For overdrafts, revolving lines, cards and letters of guarantee much is bank practice: the day
basis, the accrual dates, whether a started period is charged in full. Those choices change the
answer, so each is an explicit argument and every result lists the conventions it used.

A letter of guarantee of 10,000,000 TL at 2.40 % a year, issued 15 January, reduced by 4,000,000 on
15 June, returned on 2 November:

```python
from eqlx_bankmath import tools

letter = dict(
    amount=10_000_000,
    commission_rate="0.024",
    issue_date="2026-01-15",
    bsmv="0.05",
    expiry_date="2027-01-15",
    return_date="2026-11-02",
)
reductions = [["2026-06-15", 4_000_000]]

full = tools.guarantee_commission(**letter, options={"reductions": reductions})
by_days = tools.guarantee_commission(**letter, options={"reductions": reductions, "started_period": "pro_rata"})

full["totals"]["cost"], full["effective_annual_cost_percent"]  # 201600.0, 3.0883
by_days["totals"]["cost"], by_days["effective_annual_cost_percent"]  # 164500.0, 2.52
```

The same letter costs 201,600.00 TL when started quarters are charged in full without refund, and
164,500.00 TL when the commission follows the days outstanding. Neither is "the" answer; the tool
says which one it computed.

A card statement of 12,000 TL with a minimum of 2,400 TL, of which only 1,000 TL is paid: the
Regulation charges default interest on the unpaid part of the minimum, the Law's wording on the
whole remaining balance. `card_statement_interest` returns 372.36 TL of interest under the first
reading and 392.52 TL under the second (`shortfall_basis`).

## How it is verified

| What | Checked against |
|---|---|
| Consumer instalment plan, 12 and 36 months | Tüketici Kredisi Sözleşmeleri Yönetmeliği, Ek-1 and Ek-2: every figure, to the kuruş |
| Housing loan plan | Konut Finansmanı Sözleşmeleri Yönetmeliği, Ek-1 |
| Early repayment, partial prepayment, late interest | the same regulation, Ek-2, Ek-4, Ek-5 |
| Annual cost rate | the two annexes; Directive 98/7/EC Annex III (eight examples) |
| Levy rates by date | Presidential Decisions 5729, 7345, 10094; Decision 2010/974 |
| Commercial early repayment fee | TCMB implementation instruction: its two worked examples |
| Card rate ceilings | TCMB table valid from 1 November 2026 |
| Card minimum payment, overdraft limit | BDDK decisions 10222, 10970, 11581 and 11365 |
| Compounded reference rate | Borsa İstanbul's published TLREF example |
| Card statements, overdraft months | published bank examples, and arithmetic shown in the tests |
| Daily-balance interest, discounting, guarantees | textbook examples and arithmetic shown in the tests |

Where a printed official figure is itself inconsistent, the test asserts the correct value and says
why. Example: the regulation's early repayment example prints KKDF as 45.23 where 301.59 x 15 % is
45.24, and its annual rate as 16.4870 % where its own cash flows give 16.4872 %.

The first rows of the table are official worked examples. The last two are not: no regulator
publishes a full card statement or a commission schedule, so those parts are checked against their
definitions, not against an official number.

## Limits

A calculation, not an offer, a quote or legal advice. Levy rates and ceilings change by decree; the
tables carry the date they were last checked. Not covered: letters of credit, KGF guarantees, card
debt restructuring, instalment cash advances, FX revaluation, BDDK maturity and loan-to-value
tables. See [LIMITS.md](LIMITS.md).

## References

- Tüketici Kredisi Sözleşmeleri Yönetmeliği (Official Gazette 22.05.2015, no. 29363) and its annexes;
  Konut Finansmanı Sözleşmeleri Yönetmeliği (28.05.2015, no. 29369); Law 6502.
- Law 6802 (BSMV); KKDF decisions 88/12944, 2010/974 and Presidential Decision 10094.
- TCMB Communiqués 2020/3, 2020/4, 2020/7, 2020/16 and their implementation instructions.
- Law 5464 and the Regulation on Bank Cards and Credit Cards; BDDK Board decisions on minimum
  payments and overdraft limits.
- Turkish Commercial Code Article 8; Law 3095; Turkish Code of Obligations Articles 121 and 388.
- Directive 98/7/EC, Annex III; Directive 2008/48/EC, Annex I.
- Borsa İstanbul, TLREF rules.

## License

Apache-2.0. Part of [eqlx.org](https://eqlx.org): deterministic tools for AI agents in credit and
finance. Questions: research@eqlx.ai.
