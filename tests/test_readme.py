"""The numbers printed in the README are real."""

from pathlib import Path

from eqlx_bankmath import tools
from eqlx_bankmath.cli import _plan_text

README = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")


def test_plan_shown_in_the_readme():
    d = tools.loan_plan(100000, "0.0399", 24, product="consumer", disbursed_on="2026-11-10", fee=500)
    head = "\n".join(_plan_text(d).split("\n")[:3])
    assert head in README
    assert "59.92 % a year" in README and "84.55 %" in README


def test_guarantee_example():
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
    assert (full["totals"]["cost"], full["effective_annual_cost_percent"]) == (201600.0, 3.0883)
    assert (by_days["totals"]["cost"], by_days["effective_annual_cost_percent"]) == (164500.0, 2.52)
    for shown in ("201600.0, 3.0883", "164500.0, 2.52", "201,600.00 TL", "164,500.00 TL"):
        assert shown in README


def test_card_example():
    args = (12000, 2400, "2026-10-15", "2026-10-25", "2026-11-15", "0.0325", "0.0355")
    kw = dict(payments=[["2026-10-25", 1000]], kkdf="0.15", bsmv="0.15")
    regulation = tools.card_statement_interest(*args, **kw, options={"new_purchases": 3000})
    law = tools.card_statement_interest(
        *args, **kw, options={"new_purchases": 3000, "shortfall_basis": "whole_balance"}
    )
    assert (regulation["interest"], law["interest"]) == (372.36, 392.52)
    assert "372.36 TL" in README and "392.52 TL" in README


def test_every_tool_is_listed():
    assert "Eighteen read-only tools" in README and len(tools.TOOLS) == 18
    for name in tools.TOOLS:
        assert f"`{name}`" in README
