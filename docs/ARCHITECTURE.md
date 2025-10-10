# FHIRLINT — Architecture

> Validate FHIR R4/R5 resources and bundles against profiles (US Core, etc.) with precise, line-level error reporting.

```
input ──▶ collect ──▶ rules/analyzers ──▶ score ──▶ findings ──▶ table · json
                              │                          │
                         (this repo)                 MCP tool (agents)
```

- **collect** normalizes the target (file/dir/API) into records.
- **rules/analyzers** apply the heuristics shipped in `fhirlint/core.py`.
- **score** ranks by severity.
- **MCP server** (`fhirlint mcp`) exposes `scan` for Cognis.Studio agents.

Extend by adding a rule + a test + a `demos/NN-*/SCENARIO.md`. See [CONTRIBUTING.md](../CONTRIBUTING.md).
