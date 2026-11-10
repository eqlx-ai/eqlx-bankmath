"""Cases found by an independent review of version 0.1 before release; each was a defect."""

import json
from decimal import Decimal as D

import pytest

from eqlx_bankmath import costrate, installment, tools
from eqlx_bankmath.cli import main
from eqlx_bankmath.errors import InputError


def test_one_levy_given_with_a_product_overrides_only_that_levy():
    kw = dict(
        principal=100000,
        monthly_rate="0.0399",
        instalments=24,
        product="consumer",
        disbursed_on="2026-11-10",
        rows=False,
    )
    both = tools.loan_plan(**kw)
    only_bsmv = tools.loan_plan(bsmv="0.15", **kw)
    assert (only_bsmv["kkdf_rate"], only_bsmv["bsmv_rate"], only_bsmv["instalment"]) == (0.15, 0.15, both["instalment"])
    assert (
        only_bsmv["levies"]["bsmv_basis"] == "given by the caller" and "2010/974" in only_bsmv["levies"]["kkdf_basis"]
    )
    lower = tools.loan_plan(kkdf="0.10", **kw)
    assert (lower["kkdf_rate"], lower["bsmv_rate"]) == (0.10, 0.15)
    with pytest.raises(InputError, match="both kkdf and bsmv"):
        tools.loan_plan(100000, "0.0399", 24, bsmv="0.15")


def test_kkdf_on_a_foreign_currency_loan_is_charged_on_the_principal_once():
    d = tools.loan_plan(100000, "0.01", 12, product="commercial_fx", disbursed_on="2026-01-01", rows=False)
    assert (d["kkdf_rate"], d["total_kkdf"], d["kkdf_at_drawdown"], d["fee_at_drawdown"]) == (0.0, 0.0, 1000.0, 1000.0)
    assert d["total_repayment"] == pytest.approx(d["instalment"] * 11 + d["last_instalment"] + 1000)


def test_long_first_period_lets_the_balance_grow_in_the_first_month():
    # at 3.99 % a month with today's levies, 45 days of interest exceed the instalment
    p = installment.plan(100000, "0.0399", 24, kkdf="0.15", bsmv="0.15", first_period_days=45)
    assert p.rows[0].interest == D("5985.00") and p.rows[0].principal < 0 and p.rows[0].balance > 100000
    assert p.rows[-1].balance == 0 and p.total("principal") == 100000
    base = installment.plan(100000, "0.0399", 36, kkdf="0.15", bsmv="0.15")
    for days in (1, 10, 20, 29):
        after = installment.prepay(base, 5, 10000, days_since_last_due=days)
        assert after.n == 30 and after.rows[-1].balance == 0 and 0 < after.instalment < base.instalment


def test_due_dates_stay_on_the_same_day_after_an_odd_first_period():
    p = installment.plan(100000, "0.03", 6, start="2026-01-15", first_period_days=31)
    assert [r.date.isoformat() for r in p.rows] == [
        "2026-02-15",
        "2026-03-15",
        "2026-04-15",
        "2026-05-15",
        "2026-06-15",
        "2026-07-15",
    ]


def test_rounding_never_repays_more_than_is_owed():
    p = installment.plan(100, 0, 600)
    assert min(r.balance for r in p.rows) == 0 and min(r.payment for r in p.rows) == 0 and p.total("principal") == 100
    q = installment.plan(1, "0.01", 150, method="equal_principal")
    assert min(r.payment for r in q.rows) >= 0 and q.rows[-1].balance == 0


def test_the_regular_instalment_of_a_very_long_plan():
    p = installment.plan(1000000, "0.03", 600, kkdf="0.15", bsmv="0.15")
    assert p.instalment == D("39000.00")  # the level instalment, not the final settlement
    assert costrate.as_percent(p.annual_cost_rate()) == D("58.2656")


def test_partial_prepayment_is_refused_for_plans_it_would_misshape():
    with pytest.raises(InputError, match="equal-instalment"):
        installment.prepay(installment.plan(100000, "0.02", 24, balloon=50000), 3, 5000)
    with pytest.raises(InputError, match="equal-instalment"):
        installment.prepay(installment.plan(100000, "0.02", 24, method="bullet"), 3, 5000)
    with pytest.raises(InputError, match="equal-instalment"):
        installment.prepay(installment.plan(100000, "0.02", 24, interest_only_periods=6), 3, 5000)


def test_implied_rate_above_the_bracket_is_an_error_not_a_wrong_answer():
    with pytest.raises(InputError, match="above 100 %"):
        installment.implied_monthly_rate(100, 500, 2)


def test_cost_rate_refuses_flows_that_have_no_single_rate():
    with pytest.raises(InputError, match="do not bracket a single rate"):
        costrate.annual_cost_rate([(0, 100), (2, 132)], [(1, 230)])  # roots at 10 % and 20 %
    with pytest.raises(InputError):
        costrate.annual_cost_rate([(0, 100)], [(300, 200)])


def test_money_has_two_decimals_and_a_sane_size():
    for bad in ("1000.005", "1e40", "1e999", "NaN", "abc", 1e308):
        with pytest.raises(InputError):
            installment.plan(bad, "0.01", 12)
    with pytest.raises(InputError):
        installment.plan(1000, "1e-999", 12)
    with pytest.raises(InputError, match="must not exceed 1200"):
        installment.plan(1000, "0.01", 10**40)


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (
            "overdraft_interest",
            dict(
                opening_balance=0,
                movements="abc",
                period_start="2026-10-01",
                period_end="2026-10-31",
                monthly_rate="0.04",
            ),
        ),
        (
            "overdraft_interest",
            dict(
                opening_balance=0,
                movements=[["2026-10-02"]],
                period_start="2026-10-01",
                period_end="2026-10-31",
                monthly_rate="0.04",
            ),
        ),
        (
            "revolving_line",
            dict(
                opening_balance=0,
                movements=[{"date": "2026-01-02"}],
                start="2026-01-01",
                end="2026-03-31",
                annual_rate="0.4",
            ),
        ),
        ("balance_interest", dict(balances=None, annual_rate="0.4")),
        ("floating_rate_plan", dict(principal=1000, instalments=12, rates_by_instalment="x")),
        ("compounded_reference_rate", dict(observations=[[1]])),
        (
            "card_statement_interest",
            dict(
                statement_balance=1000,
                minimum=200,
                statement_date="2026-10-15",
                due_date="2026-10-25",
                next_statement_date="2026-11-15",
                contractual_rate="0.03",
                default_rate="0.033",
                payments="x",
            ),
        ),
        (
            "guarantee_commission",
            dict(
                amount=1000000,
                commission_rate="0.02",
                issue_date="2026-01-01",
                bsmv="0.05",
                expiry_date="2027-01-01",
                options={"reductions": "x"},
            ),
        ),
        (
            "guarantee_commission",
            dict(
                amount=1000000,
                commission_rate="0.02",
                issue_date="2026-01-01",
                bsmv="0.05",
                expiry_date="2027-01-01",
                options={"period_months": 10**6},
            ),
        ),
        (
            "guarantee_commission",
            dict(),
        ),
        ("fee_cap_check", dict(kind="commercial_allocation", arguments="abc")),
        ("fee_cap_check", dict(kind="consumer_allocation", arguments={})),
        ("fee_cap_check", dict(kind="consumer_allocation", arguments={"principal": -1000})),
        ("fee_cap_check", dict(kind="consumer_allocation", arguments={"principal": 1000, "on": "2019-01-01"})),
        ("levies", dict(product=[], disbursed_on="2026-01-01")),
        ("card_minimum_payment", dict(statement_balance=1000, card_limit="1e999", on="2026-11-10")),
        ("spot_loan", dict(principal="1e40", annual_rate="0.4", days=90)),
        ("loan_plan", dict(principal=1000, monthly_rate="0.01", instalments=10**40)),
        ("loan_affordability", dict(monthly_rate="0.01", instalments=10**40, instalment=100)),
    ],
)
def test_bad_input_is_reported_with_a_reason_never_a_traceback(tool, args):
    with pytest.raises(InputError) as info:
        tools.TOOLS[tool](**args)
    assert len(str(info.value)) > 10


def test_consumer_allocation_ceiling_rounds_half_up():
    # 0.5 % of 1,001 is 5.005 and of 1,003 is 5.015: half-up gives 5.01 and 5.02
    assert tools.fee_cap_check("consumer_allocation", {"principal": 1001})["maximum_fee"] == 5.01
    assert tools.fee_cap_check("consumer_allocation", {"principal": 1003})["maximum_fee"] == 5.02
    assert tools.fee_cap_check(
        "allocation_with_non_cash",
        {"cash_limit": 10000000, "non_cash_limit": 10000000, "months": 12, "on": "2026-11-10"},
    )


def test_command_line_never_prints_a_traceback(capsys):
    for argv in (
        ["plan", "1e40", "0.0399", "24"],
        ["plan", "100000", "0.0399", "24", "--kkdf", ""],
        ["call", "balance_interest", '{"balances": "x", "annual_rate": "0.4"}'],
    ):
        assert main(argv) == 2
        assert capsys.readouterr().err.startswith("error:")
    assert (
        main(
            [
                "plan",
                "100000",
                "0.0399",
                "24",
                "--product",
                "consumer",
                "--date",
                "2026-11-10",
                "--kkdf",
                "0.15",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["bsmv_rate"] == 0.15


def test_revolving_flags_must_be_booleans():
    from eqlx_bankmath import revolving

    with pytest.raises(InputError, match="true or false"):
        tools.TOOLS["revolving_line"](1000, [], "2024-01-01", "2024-03-31", "0.3", options={"count_end_day": "no"})
    with pytest.raises(InputError, match="true or false"):
        revolving.line(1000, [], "2024-01-01", "2024-03-31", "0.3", merchant="no")
    with pytest.raises(InputError, match="true or false"):
        revolving.utilisation_fee_cap(1000, 90, revolving="no")


def test_monthly_capitalisation_is_flagged_also_in_the_last_period():
    from eqlx_bankmath import revolving

    out = revolving.line(1000000, [], "2026-01-01", "2026-02-28", "0.36", accrual="monthly")
    assert len(out["warnings"]) == 1 and "8(2)" in out["warnings"][0]
    quarterly = revolving.line(1000000, [], "2026-01-01", "2026-06-30", "0.36")
    assert quarterly["warnings"] == []
    stub = revolving.line(
        1000000, [], "2026-01-01", "2026-04-15", "0.36"
    )  # stops mid-quarter: not a capitalisation date
    assert stub["warnings"] == []


def test_utilisation_cap_covered_foreign_currency_loans_until_february_2026():
    from eqlx_bankmath import revolving

    before = revolving.utilisation_fee_cap(1000000, 360, turkish_lira=False, on="2025-12-15")
    after = revolving.utilisation_fee_cap(1000000, 360, turkish_lira=False, on="2026-02-01")
    assert before["allowed_maximum"] == 11000.0 and after["allowed_maximum"] is None


def test_guarantee_refund_keeps_the_commission_on_what_stays_outstanding():
    from eqlx_bankmath import guarantee

    # 1,000,000 at 2.4 %: quarter charged in full = 6,000. 990,000 released on day 1 of a 92-day quarter.
    # refund = 6,000 x 0.99 x 91/92 = 5,875.43; 124.57 stays for the 10,000 outstanding and the first day.
    s = guarantee.commission_schedule(
        1000000,
        "0.024",
        "2026-07-01",
        bsmv=0,
        expiry_date="2026-10-01",
        reductions=[("2026-07-02", 990000)],
        refund_on_reduction=True,
    )
    assert (s.rows[0].collected, s.rows[0].refund, s.rows[0].commission) == (D("6000.00"), D("5875.43"), D("124.57"))
    # returned after two days: refund 6,000 x 90/92 = 5,869.57, so two days are paid for (130.43)
    back = guarantee.commission_schedule(
        1000000,
        "0.024",
        "2026-07-01",
        bsmv=0,
        expiry_date="2026-10-01",
        return_date="2026-07-03",
        refund_on_return=True,
    )
    assert (back.rows[0].refund, back.rows[0].commission) == (D("5869.57"), D("130.43"))
