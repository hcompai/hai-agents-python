<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
</p>

# hai-agents

Python SDK for [H Company's Agent Platform](https://hcompany.ai). Sync and async clients, fully typed with Pydantic v2.

## Quickstart

Install from a repository checkout:

```bash
git clone https://github.com/hcompai/hai-agents-python.git
cd hai-agents-python
pip install ./packages/sdk
```

The public `hai-agents` package is not yet published to PyPI. Until it is,
install from a repository checkout as shown above.

```python
from hai_agents import Client, Agent, SessionRequest
from hai_agents.api.sessions import create_session
from hai_agents.models.browser import Browser
from hai_agents.models.user_message_event import UserMessageEvent

client = Client(api_key="hk-...")

session = create_session.sync(
    client=client,
    body=SessionRequest(
        agent=Agent(
            name="my-agent",
            description="A demo agent.",
            instructions="Reply concisely.",
            environments=[Browser(id="browser", kind="web",
                                  headless=True,
                                  width=1280, height=800,
                                  start_url="https://bing.com")],
        ),
        messages=[UserMessageEvent(message="What is the weather in Paris?")],
        max_steps=12,
    ),
)
print(session.id)
```

Grab a key at [portal.hcompany.ai](https://portal.hcompany.ai). The default `base_url` is the production endpoint; pass `base_url=` to point at staging.

## Poll, stream, send

```python
from hai_agents.api.sessions import get_session_status, get_session_changes, send_session_messages

status = get_session_status.sync(client=client, id=session.id)

# Long-poll for new events
changes = get_session_changes.sync(client=client, id=session.id, from_index=0)

# Inject a message mid-run (single event, or a UserMessageBatch for multiple)
send_session_messages.sync(
    client=client,
    id=session.id,
    body=UserMessageEvent(message="Actually, switch to Lyon."),
)
```

## Async

```python
from hai_agents import AsyncClient
from hai_agents.api.sessions import list_session_events

client = AsyncClient(api_key="hk-...")
events = await list_session_events.asyncio(client=client, id="...")
```

## Memories, skills, environments, agents

CRUD endpoints for each catalog live under `hai_agents.api.{memories,skills,environments,agents}`.

## Errors

```python
from hai_agents.errors import UnexpectedStatus

try:
    get_session_status.sync(client=client, id="missing")
except UnexpectedStatus as e:
    print(e.status_code, e.content)
```

## Requirements

Python 3.10+. Runtime deps: `httpx`, `pydantic>=2`, `python-dateutil`, `attrs`.
