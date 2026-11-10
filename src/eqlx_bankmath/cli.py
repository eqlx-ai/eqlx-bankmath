"""Command line: ``bankmath plan | levies | tools | call | mcp``."""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from typing import Any

from . import __version__
from .errors import InputError
from .tools import TOOLS, levies, loan_plan


def _emit(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _plan_text(d: dict[str, Any]) -> str:
    lines = [
        f"instalment {d['instalment']:,.2f}   last {d['last_instalment']:,.2f}   "
        f"total repayment {d['total_repayment']:,.2f}   total cost {d['total_cost']:,.2f}",
        f"annual cost rate {d['annual_cost_rate_percent']:.4f} %   "
        f"(monthly rate alone: {d['annual_rate_from_monthly_rate_percent']:.4f} % a year)",
        f"KKDF {d['kkdf_rate']:.2%}   BSMV {d['bsmv_rate']:.2%}   levies: "
        + str(d["levies"].get("source") or f"{d['levies'].get('kkdf_basis')}; {d['levies'].get('bsmv_basis')}"),
        "",
        f"{'#':>3} {'date':<10} {'payment':>12} {'interest':>11} {'KKDF':>9} {'BSMV':>9} "
        f"{'principal':>12} {'balance':>13}",
    ]
    for r in d.get("rows", []):
        lines.append(
            f"{r['number']:>3} {r['date'] or '':<10} {r['payment']:>12,.2f} {r['interest']:>11,.2f} "
            f"{r['kkdf']:>9,.2f} {r['bsmv']:>9,.2f} {r['principal']:>12,.2f} {r['balance']:>13,.2f}"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bankmath", description="Deterministic bank product arithmetic for Türkiye.")
    p.add_argument("--version", action="version", version=f"eqlx-bankmath {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("plan", help="repayment plan of an instalment loan")
    s.add_argument("principal")
    s.add_argument("monthly_rate", help="as a fraction: 0.0399 for 3.99 %%")
    s.add_argument("instalments", type=int)
    s.add_argument("--product", choices=("consumer", "housing_first_home", "commercial_tl", "commercial_fx"))
    s.add_argument("--date", help="disbursement date, e.g. 2026-11-10 (needed with --product)")
    s.add_argument("--kkdf")
    s.add_argument("--bsmv")
    s.add_argument("--fee", default="0")
    s.add_argument("--method", default="annuity", choices=("annuity", "equal_principal", "bullet"))
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("levies", help="KKDF and BSMV in force for a product on a date")
    s.add_argument("product")
    s.add_argument("date")

    sub.add_parser("tools", help="list every calculation with its arguments")

    s = sub.add_parser("call", help="run any calculation: bankmath call <tool> '<json arguments>'")
    s.add_argument("tool")
    s.add_argument("arguments", nargs="?", default="{}")

    sub.add_parser("mcp", help="start the MCP server for AI agents")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "mcp":
        from .mcp_server import build_server

        build_server().run()
        return 0
    if args.command == "plan":
        d = loan_plan(
            args.principal,
            args.monthly_rate,
            args.instalments,
            product=args.product,
            disbursed_on=args.date,
            kkdf=args.kkdf,
            bsmv=args.bsmv,
            method=args.method,
            fee=args.fee,
        )
        if args.json:
            _emit(d)
        else:
            print(_plan_text(d))
        return 0
    if args.command == "levies":
        _emit(levies(args.product, args.date))
        return 0
    if args.command == "tools":
        for name, fn in TOOLS.items():
            doc = (inspect.getdoc(fn) or "").split("\n")[0]
            print(f"{name}{inspect.signature(fn)}\n    {doc}\n")
        return 0
    if args.command == "call":
        if args.tool not in TOOLS:
            raise InputError(f"unknown tool {args.tool!r}; run 'bankmath tools'")
        try:
            kwargs = json.loads(args.arguments)
        except json.JSONDecodeError as exc:
            raise InputError(f"the arguments are not valid JSON ({exc})") from exc
        if not isinstance(kwargs, dict):
            raise InputError("the arguments must be a JSON object")
        try:
            _emit(TOOLS[args.tool](**kwargs))
        except TypeError as exc:
            raise InputError(f"{args.tool}: {exc}") from exc
        return 0
    raise InputError(f"unknown command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
