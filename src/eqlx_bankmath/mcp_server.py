"""MCP server: lets an AI agent ask for bank product arithmetic instead of doing it itself.

Every tool is a pure calculation on the numbers it is given. Nothing is read from disk, nothing is
written, nothing is sent anywhere. Start it with ``bankmath mcp``
(needs ``pip install 'eqlx-bankmath[mcp]'``).
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import __version__
from .tools import TOOLS

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)


def build_server() -> MCPServer:
    server = MCPServer(
        "eqlx-bankmath",
        version=__version__,
        instructions=(
            "Arithmetic for bank products in Türkiye, exact to the kuruş: instalment loans with KKDF and BSMV "
            "and the annual cost rate, early repayment, overdrafts and revolving lines on daily balances, spot "
            "loans, bill discounting, variable-rate plans, credit card statements, letters of guarantee, and "
            "checks against regulated fee and rate ceilings. Use these tools for every number you give a "
            "customer or a colleague; do not compute instalments, interest or cost rates yourself. Rates are "
            "fractions (0.0399 for 3.99 %), dates are ISO strings. Each result lists the conventions it used; "
            "where a convention is bank practice rather than law (day basis, accrual dates, started periods) "
            "say so, and use the bank's own convention if you know it. Levies and ceilings are dated tables: "
            "pass on the legal basis and the date the table was last checked. A result is a calculation, not "
            "an offer, a quote or legal advice."
        ),
    )
    for fn in TOOLS.values():
        server.tool(annotations=READ_ONLY)(fn)
    return server
