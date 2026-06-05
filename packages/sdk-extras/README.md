# hai-agents-extras

CLI and MCP entry points for the `hai-agents` Python SDK.

```bash
pip install hai-agents-extras
export HAI_API_KEY=hk-...
hai-agents run "Summarize the H Agent API quickstart"
hai-agents-mcp
```

The implementation lives outside the generated SDK `src/hai_agents` tree so SDK
regeneration can update the client without deleting the CLI or MCP server.
