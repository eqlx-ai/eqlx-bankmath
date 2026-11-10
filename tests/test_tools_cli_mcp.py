import asyncio
import json

import pytest

from eqlx_bankmath import tools
from eqlx_bankmath.cli import main
from eqlx_bankmath.errors import InputError


def run(capsys, *args):
    code = main([str(a) for a in args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_loan_plan_looks_up_levies_and_reports_their_basis():
    d = tools.loan_plan(100000, "0.0399", 24, product="consumer", disbursed_on="2026-11-10", fee=500)
    assert (d["instalment"], d["total_repayment"], d["kkdf_rate"], d["bsmv_rate"]) == (7379.48, 177607.76, 0.15, 0.15)
    assert d["annual_cost_rate_percent"] == pytest.approx(84.5548, abs=1e-4)
    assert "7345" in d["levies"]["bsmv_basis"] and d["levies"]["table_checked_on"] == "2026-11-10"
    assert d["rows"][0]["date"] == "2026-12-10" and len(d["rows"]) == 24
    json.dumps(d)
    # the same loan disbursed before 7 July 2023 carried 10 % BSMV
    older = tools.loan_plan(100000, "0.0399", 24, product="consumer", disbursed_on="2023-07-06", rows=False)
    assert older["bsmv_rate"] == 0.10 and older["instalment"] < d["instalment"] and "rows" not in older


def test_levies_are_never_assumed():
    plain = tools.loan_plan(10000, "0.01", 12, rows=False)
    assert plain["instalment"] == 888.49 and "none applied" in plain["levies"]["source"]
    given = tools.loan_plan(10000, "0.01", 12, kkdf="0.15", bsmv="0.05", rows=False)
    assert given["instalment"] == 899.75 and given["levies"]["source"] == "given by the caller"
    with pytest.raises(InputError, match="disbursed_on"):
        tools.loan_plan(10000, "0.01", 12, product="consumer")


def test_early_repayment_and_affordability_tools():
    kw = dict(principal=50000, monthly_rate="0.01", instalments=36, kkdf="0.15", bsmv="0.05")
    assert tools.loan_early_repayment(instalments_paid=10, **kw)["payoff"] == 38190.09
    part = tools.loan_early_repayment(
        instalments_paid=9, partial_amount=10000, days_since_last_due=21, days_to_next_due=10, **kw
    )
    assert (part["old_instalment"], part["new_instalment"], part["remaining_instalments"]) == (1718.61, 1344.88, 26)
    best = tools.loan_affordability("0.05", instalments=12, instalment=5000, kkdf="0.15", bsmv="0.15")
    assert best["largest_principal"] == 40793.66 and best["plan"]["instalment"] <= 5000
    assert (
        tools.loan_affordability("0.01", principal=10000, instalment=900, kkdf="0.15", bsmv="0.05")[
            "shortest_term_months"
        ]
        == 12
    )
    with pytest.raises(InputError, match="exactly two"):
        tools.loan_affordability("0.01", principal=10000)


def test_other_tools_return_the_module_results():
    assert tools.late_payment_interest("1245.39", "0.01", 10, kkdf="0.15", bsmv="0.05")["total"] == 6.48
    x = tools.annual_cost_rate([[0, 1000]], [[1.5, 1200]])
    assert x["annual_cost_rate_percent"] == 12.9243
    assert tools.levies("commercial_tl", "2026-11-10")["bsmv"] == 0.05
    assert tools.balance_interest([[10000, 15], [6000, 11]], "0.51")["interest"] == 306.0  # 216000 x 0.51 / 360
    assert tools.spot_loan(1000000, "0.45", 90, bsmv="0.05")["interest"] == 112500.0  # 1e6 x 0.45 x 90 / 360
    assert tools.card_minimum_payment(40000, 80000, "2026-11-10")["minimum_payment"] == 8000.0  # 20 % up to 100,000
    assert tools.card_minimum_payment(40000, 150000, "2026-11-10")["minimum_payment"] == 16000.0  # 40 % above
    caps = tools.card_rate_caps("0.0311", 20000, on="2026-11-10")
    assert json.dumps(caps) and "0.0325" in json.dumps(caps)
    g = tools.guarantee_commission(10000000, "0.024", "2026-01-01", "0.05", expiry_date="2027-01-01")
    assert g["periods"][0]["commission"] == 60000.0  # 10,000,000 x 2.4 % / 4
    check = tools.fee_cap_check("consumer_allocation", {"principal": 100000, "quoted_fee": 750})
    assert check["maximum_fee"] == 500.0 and check["exceeds"] is True
    assert tools.fee_cap_check("cash_advance", {"advance": 1000, "fee": 10})
    with pytest.raises(InputError, match="unknown kind"):
        tools.fee_cap_check("mood", {})
    with pytest.raises(InputError):
        tools.spot_loan(1000, "0.4", 90, options={"mood": 1})


def test_every_tool_is_documented_and_serialisable():
    assert len(tools.TOOLS) == 18
    for name, fn in tools.TOOLS.items():
        assert fn.__doc__ and len(fn.__doc__) > 60, name


def test_command_line(capsys):
    code, out, _ = run(capsys, "plan", 10000, "0.01", 12, "--kkdf", "0.15", "--bsmv", "0.05", "--fee", 50)
    assert code == 0 and "instalment 899.75" in out and "16.4872 %" in out and "899.81" in out
    code, out, _ = run(capsys, "plan", 10000, "0.01", 12, "--product", "consumer", "--date", "2026-11-10", "--json")
    assert json.loads(out)["bsmv_rate"] == 0.15
    code, out, _ = run(capsys, "levies", "consumer", "2022-06-11")
    assert json.loads(out)["bsmv"] == 0.1
    code, out, _ = run(
        capsys,
        "call",
        "late_payment_interest",
        '{"principal_in_instalment": "1245.39", "monthly_rate": "0.01", "days_late": 10}',
    )
    assert code == 0 and json.loads(out)["interest"] == 5.4
    code, out, _ = run(capsys, "tools")
    assert code == 0 and "guarantee_commission(" in out and "card_statement_interest(" in out


def test_command_line_errors(capsys):
    assert run(capsys, "plan", 10000, "0.01", 12, "--product", "consumer")[0] == 2
    assert run(capsys, "call", "nope")[0] == 2
    assert run(capsys, "call", "levies", "{oops")[0] == 2
    assert run(capsys, "call", "levies", "[1]")[0] == 2
    code, _, err = run(capsys, "call", "levies", '{"product": "consumer"}')
    assert code == 2 and "levies" in err
    assert run(capsys, "plan", -5, "0.01", 12)[0] == 2


mcp = pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

from eqlx_bankmath.mcp_server import build_server  # noqa: E402


def call(name, args):
    async def go():
        async with Client(build_server()) as c:
            return await c.call_tool(name, args)

    return asyncio.run(go())


def test_mcp_lists_every_tool_as_read_only():
    async def go():
        async with Client(build_server()) as c:
            return await c.list_tools()

    listed = {t.name: t for t in asyncio.run(go()).tools}
    assert set(listed) == set(tools.TOOLS)
    assert all(t.annotations.read_only_hint and not t.annotations.destructive_hint for t in listed.values())


def test_mcp_calls():
    plan = call(
        "loan_plan",
        {"principal": 10000, "monthly_rate": "0.01", "instalments": 12, "kkdf": "0.15", "bsmv": "0.05", "fee": 50},
    ).structured_content
    assert plan["instalment"] == 899.75 and plan["annual_cost_rate_percent"] == 16.4872
    od = call(
        "overdraft_interest",
        {
            "opening_balance": 0,
            "movements": [["2026-10-05", 10000], ["2026-10-20", -4000]],
            "period_start": "2026-10-01",
            "period_end": "2026-10-31",
            "monthly_rate": "0.0425",
        },
    ).structured_content
    assert od["interest"] > 0 and "conventions" in od
    assert call("loan_plan", {"principal": -1, "monthly_rate": "0.01", "instalments": 12}).is_error
    assert call("fee_cap_check", {"kind": "mood", "arguments": {}}).is_error
