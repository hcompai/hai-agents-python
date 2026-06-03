<p align="center">
  <a href="https://pypi.org/project/hai-agents/"><img src="https://img.shields.io/pypi/v/hai-agents.svg" alt="PyPI" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
</p>

# hai-agents

Python SDK for [H Company's Agent Platform](https://hcompany.ai). A fully typed, class-based client covering sessions, agents, memories, skills, and environments.

## Install

```bash
pip install hai-agents
```

Requires Python 3.9 or newer. Grab an API key at [portal.hcompany.ai](https://portal.hcompany.ai).

## Quickstart

```python
from hai_agents import Client

client = Client(token="YOUR_API_KEY")

session = client.sessions.create_session(
    agent="h/web",
    messages="What is the H1 on example.com?",
    max_steps=10,
    max_time_s=150,
)

print(session.id)
```

An `AsyncClient` with the same surface is available for asyncio code.

## Run a task to completion

`run_session_until_done` creates a session and polls until the agent reaches a
terminal state, returning the terminal `status`, accumulated events, and final answer.

```python
from hai_agents import run_session_until_done

result = run_session_until_done(
    client,
    agent="h/web",
    messages="What is the H1 on example.com?",
    timeout_seconds=180,        # overall wall-clock budget
    poll_backoff_seconds=1.0,   # delay between polls, on top of the server long-poll
    include_events=True,        # set False to poll status only, without streaming events
)

print(result.status, result.answer)
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

## Messages and feedback

```python
from hai_agents import SendSessionMessagesRequestBody_UserMessage

client.sessions.send_session_messages(
    session.id,
    request=SendSessionMessagesRequestBody_UserMessage(
        message="Keep the answer under one sentence.",
    ),
)

client.sessions.submit_session_feedback(
    session.id,
    success=True,
    message="The answer matched the page heading.",
)
```

## Cancelling a session

`cancel_session` asks the platform to interrupt the run. The session may still
report `running` briefly while the worker stops; poll until it reaches a terminal
state such as `interrupted`.

```python
client.sessions.cancel_session(session.id)
```

## Request size limit

The platform rejects request bodies above 5MB. `run_session_until_done` enforces
this on the create payload; for ad-hoc requests, validate first to fail fast with
a clear message instead of a server error.

```python
from hai_agents import MAX_REQUEST_BYTES, assert_request_under_limit

assert_request_under_limit({"agent": "h/web", "messages": messages})
print(f"limit: {MAX_REQUEST_BYTES} bytes")
```
