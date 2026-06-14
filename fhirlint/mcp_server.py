"""FHIRLINT MCP server — exposes lint_text() as an MCP tool for Cognis.Studio."""
from __future__ import annotations
import json
import sys
from fhirlint.core import lint_text

def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-fhirlint[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print(
            "Install the MCP extra: pip install 'cognis-fhirlint[mcp]'",
            file=sys.stderr,
        )
        return 1
    app = FastMCP("fhirlint")

    @app.tool()
    def fhirlint_scan(target: str) -> str:
        """Validate a FHIR R4 JSON resource or bundle. Returns JSON findings."""
        if not isinstance(target, str) or not target.strip():
            return json.dumps({"error": "target must be a non-empty JSON string"})
        findings = lint_text(target)
        return json.dumps([f.to_dict() for f in findings], indent=2)

    app.run()
    return 0
