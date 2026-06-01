<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
</p>

# hai-agents-python

Python developer libraries and tools for [H Company's Agent Platform](https://hcompany.ai).

## Packages

| Package | Description |
| --- | --- |
| [`packages/sdk`](packages/sdk) | Python SDK source - sync and async clients, fully typed with Pydantic v2. |

Do not install `agent-platform` from public PyPI yet: that name currently
belongs to an unrelated package and does not provide this SDK's
`agent_platform` module. Install from this repository until an H-owned public
package is available.

## Development

This repo is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/). From the root:

```bash
uv sync
uv run pytest packages/sdk/tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md).
