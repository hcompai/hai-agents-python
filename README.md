<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
</p>

# hai-agents-python

Python developer libraries and tools for [H Company's Agent Platform](https://hcompany.ai).

## Packages

| Package | Description |
| --- | --- |
| [`packages/sdk`](packages/sdk) | Python SDK — sync and async clients, fully typed with Pydantic v2. Packaged as `agent-platform`. |

## Development

This repo is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/). From the root:

```bash
uv sync
uv run pytest packages/sdk/tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md).
