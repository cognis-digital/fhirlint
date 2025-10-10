"""FHIRLINT MCP server — exposes scan() as an MCP tool for Cognis.Studio."""
from __future__ import annotations
from fhirlint.core import scan, to_json

def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-fhirlint[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print("Install the MCP extra: pip install 'cognis-fhirlint[mcp]'")
        return 1
    app = FastMCP("fhirlint")

    @app.tool()
    def fhirlint_scan(target: str) -> str:
        """Validate FHIR R4/R5 resources and bundles against profiles (US Core, etc.) with precise, line-level error reporting.. Returns JSON findings."""
        return to_json(scan(target))

    app.run()
    return 0
