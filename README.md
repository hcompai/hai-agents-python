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
  Python SDK for the H Company Agent API. Launch autonomous agents powered by Holo, stream their progress, and steer them mid-run.
</p>

<p align="center">
  <b><a href="https://hub.hcompany.ai/agent-api">Documentation</a></b>
  &nbsp;·&nbsp;
  <a href="https://portal.hcompany.ai">Get an API key</a>
  &nbsp;·&nbsp;
  <a href="https://pypi.org/project/hai-agents/">PyPI</a>
  &nbsp;·&nbsp;
  <a href="https://hcompany.ai">H Company</a>
</p>

## Installation

```bash
pip install hai-agents
```

Requires Python 3.10 or newer. Grab an API key at [portal.hcompany.ai](https://portal.hcompany.ai).

## Quickstart

List the agents available to your account, then launch one with a task described in plain language. Built-in agents, such as a web surfer that ships with its own browser, live under the `h/` namespace. `run_session_until_done` polls until the agent finishes and returns the final answer.

```python
from hai_agents import Client, run_session_until_done

client = Client(token="YOUR_API_KEY")

agents = client.agents.list_agents().items

result = run_session_until_done(
    client,
    agent=agents[0].name,
    messages="What are the top 3 stories on Hacker News right now?",
)

print(result.status)  # "completed"
print(result.answer)
```

An `AsyncClient` mirrors this API for asyncio. Streaming progress, steering a live session, regions, structured output, and error handling are all covered in the documentation.

## Documentation

Guides, core concepts, and the full API reference live at **[hub.hcompany.ai/agent-api](https://hub.hcompany.ai/agent-api)**.

- [Quickstart](https://hub.hcompany.ai/agent-api/quickstart)
- [Observe and steer a session](https://hub.hcompany.ai/agent-api/observe-and-steer)
- [Multi-agent orchestration](https://hub.hcompany.ai/agent-api/multi-agent)

## License

[MIT](LICENSE)
