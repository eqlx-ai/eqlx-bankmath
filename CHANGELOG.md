# Changelog

## 0.1.0

First release.

- Exact decimal arithmetic for money; half-up rounding to the kuruş.
- Instalment plans (annuity, equal principal, bullet; interest-only periods, balloon, odd first
  period) with KKDF and BSMV on interest; annual cost rate; early repayment, partial prepayment,
  late interest, housing prepayment compensation ceiling; largest loan, shortest term, implied rate.
- Dated tables of levy rates and fee ceilings with their legal basis.
- Daily-balance interest (interest numbers); retail overdraft; revolving lines and current accounts
  over several accrual periods; spot loans.
- Bill discounting; interest collected in advance; variable-rate plans; compounded reference rate.
- Commercial early repayment fee ceiling by disbursement date.
- Credit cards: minimum payment, rate ceilings, statement interest under two readings of a shortfall.
- Letters of guarantee: commission schedule under explicit conventions; fee ceiling checks.
- Command line `bankmath` and an MCP server with eighteen read-only tools.
