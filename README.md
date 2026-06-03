<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://github.com/hcompai/hai-agents-python/blob/main/assets/banner-dark.gif?raw=true" />
    <img src="https://github.com/hcompai/hai-agents-python/blob/main/assets/banner-light.gif?raw=true" alt="H Agent API" width="700" />
  </picture>
</p>

<p align="center">
  <a href="https://pypi.org/project/hai-agents/"><img src="https://img.shields.io/pypi/v/hai-agents.svg" alt="PyPI" /></a>
  <a href="https://pypi.org/project/hai-agents/"><img src="https://img.shields.io/pypi/pyversions/hai-agents.svg" alt="Python versions" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
</p>

<p align="center">
  Python SDK for the <a href="https://hcompany.ai">H Company</a> <a href="https://hub.hcompany.ai/agent-api">Agent API</a>. Launch autonomous agents powered by Holo, stream their progress, and steer them mid-run.
</p>

<p align="center">
  <b><a href="https://hub.hcompany.ai/agent-api">Documentation</a></b>
  &nbsp;·&nbsp;
  <a href="https://portal.hcompany.ai">Get an API key</a>
  &nbsp;·&nbsp;
  <a href="https://pypi.org/project/hai-agents/">PyPI</a>
  &nbsp;·&nbsp;
  <a href="https://github.com/hcompai/hai-agents-ts">TypeScript SDK</a>
  &nbsp;·&nbsp;
  <a href="https://hcompany.ai">H Company</a>
</p>

## Installation

```bash
pip install hai-agents
```

Requires Python 3.10 or newer. Grab an API key at [portal.hcompany.ai](https://portal.hcompany.ai).

## Quickstart

Launch the built-in `h/web-surfer-holo3-1-35b` agent, which ships with its own browser, and describe the task in plain language. `run_session_until_done` polls until the agent finishes and returns the final answer.

```python
from hai_agents import Client, run_session_until_done

client = Client(token="YOUR_API_KEY")

result = run_session_until_done(
    client,
    agent="h/web-surfer-holo3-1-35b",
    messages="What are the top 3 stories on Hacker News right now?",
)

print(result.status)  # "completed"
print(result.answer)
```

An `AsyncClient` mirrors this API for asyncio.

## Documentation

Guides, core concepts, and the full API reference live at **[hub.hcompany.ai/agent-api](https://hub.hcompany.ai/agent-api)**, covering streaming progress, steering a live session, regions, structured output, and error handling.

## License

[MIT](LICENSE)
