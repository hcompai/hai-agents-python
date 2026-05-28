<p align="center">
  <a href="https://pypi.org/project/agent-platform/"><img src="https://img.shields.io/pypi/v/agent-platform.svg" alt="PyPI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
</p>

# agent-api

Official client SDKs for [H Company's Agent Platform](https://hcompany.ai).

| Language | Package | Path |
|---|---|---|
| Python | [`agent-platform`](https://pypi.org/project/agent-platform/) | [`python/`](./python) |

## Quickstart

```bash
pip install agent-platform
```

```python
from agent_platform import Client

client = Client(api_key="hk-...")
```

Grab a key at [portal.hcompany.ai](https://portal.hcompany.ai). See [`python/README.md`](./python/README.md) for the full walkthrough.
