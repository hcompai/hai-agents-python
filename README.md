<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
</p>

# hai-agents-python

Python developer libraries and tools for [H Company's Agent Platform](https://hcompany.ai). The TypeScript counterpart lives in [`hai-agents-ts`](https://github.com/hcompai/hai-agents-ts).

## Packages

| Package | Description |
| --- | --- |
| [`packages/sdk`](packages/sdk) | Python SDK — sync and async clients, fully typed with Pydantic v2. Published to PyPI as [`agent-platform`](https://pypi.org/project/agent-platform/). |

CLI and MCP server packages will land here as additional workspace members.

## Development

This repo is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/). From the root:

```bash
uv sync           # install every package + dev tools into one venv
uv run pytest packages/sdk/tests
```

The SDK in `packages/sdk/src/` is generated from the platform's OpenAPI schema; see [CONTRIBUTING.md](CONTRIBUTING.md).
