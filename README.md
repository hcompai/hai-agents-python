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

## Install

```bash
pip install hai-agents
```

Requires Python 3.10 or newer. Grab an API key at [portal.hcompany.ai](https://portal.hcompany.ai).

## Quickstart

Launch the built-in `h/web-surfer-holo3-1-35b` agent, which ships with its own
browser, and describe the task in plain language. `run_session_until_done` polls
until the agent reaches a terminal state and returns the final answer.

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

Tune the run with `timeout_seconds`, `poll_backoff_seconds`, and `include_events`.
An `AsyncClient` (with `async_run_session_until_done`) mirrors this surface for asyncio.

## Create a session and poll it yourself

For finer control, create the session and read it directly. `get_session_status`
is a lightweight liveness check; the final `answer` lands in `get_session_changes`.

```python
session = client.sessions.create_session(
    agent="h/web-surfer-holo3-1-35b",
    messages="What are the top 3 stories on Hacker News right now?",
)

status = client.sessions.get_session_status(session.id)
print(status.status, status.steps)

changes = client.sessions.get_session_changes(session.id, from_index=0)
print(changes.answer)
```

## Steer a running session

Send a message to redirect the agent mid-run, or record feedback once it finishes.

```python
from hai_agents import SendSessionMessagesRequestBody_UserMessage

client.sessions.send_session_messages(
    session.id,
    request=SendSessionMessagesRequestBody_UserMessage(
        message="Only consider stories posted in the last 24 hours.",
    ),
)

client.sessions.submit_session_feedback(
    session.id,
    success=True,
    message="The answer matched the front page.",
)
```

`cancel_session` asks the platform to interrupt the run. The session may still
report `running` briefly while the worker stops; poll until it reaches a terminal
state such as `interrupted`.

```python
client.sessions.cancel_session(session.id)
```

## Error handling

Operations raise `ApiError` on a non-2xx response; inspect `status_code` and `body`.

```python
from hai_agents.core import ApiError

try:
    session = client.sessions.get_session(session_id)
    print(session.status)
except ApiError as err:
    print(err.status_code, err.body)
    raise
```

## Regions

The client targets the EU region by default. Select a region with `environment`,
or point at a custom URL with `base_url`.

```python
from hai_agents import Client, HaiAgentsEnvironment

us_client = Client(token="YOUR_API_KEY", environment=HaiAgentsEnvironment.US)

proxied = Client(token="YOUR_API_KEY", base_url="https://my-proxy.example.com")
```

## Request size limit

The platform rejects request bodies above 5MB. `run_session_until_done` enforces
this on the create payload; for ad-hoc requests, validate first to fail fast with
a clear message instead of a server error.

```python
from hai_agents import MAX_REQUEST_BYTES, assert_request_under_limit

assert_request_under_limit({"agent": "h/web-surfer-holo3-1-35b", "messages": messages})
print(f"limit: {MAX_REQUEST_BYTES} bytes")
```

## Documentation

- [Agent API documentation](https://hub.hcompany.ai/agent-api): guides, core concepts, and the full API reference
- [Developer portal](https://portal.hcompany.ai): manage API keys and usage
- [H Company](https://hcompany.ai)

## License

[MIT](LICENSE)
