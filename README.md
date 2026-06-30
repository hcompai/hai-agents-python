<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://github.com/hcompai/hai-agents-python/blob/main/assets/banner-dark.gif?raw=true" />
    <img src="https://github.com/hcompai/hai-agents-python/blob/main/assets/banner-light.gif?raw=true" alt="Computer-Use Agents" width="700" />
  </picture>
</p>

<p align="center">
  <a href="https://pypi.org/project/hai-agents/"><img src="https://img.shields.io/pypi/v/hai-agents.svg" alt="PyPI" /></a>
  <a href="https://pypi.org/project/hai-agents/"><img src="https://img.shields.io/pypi/pyversions/hai-agents.svg" alt="Python versions" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT" /></a>
</p>

<p align="center">
  Python SDK for <a href="https://hcompany.ai">H Company</a>'s <a href="https://hub.hcompany.ai/computer-use-agents">Computer-Use Agents</a>.
</p>

<p align="center">
  <b><a href="https://hub.hcompany.ai/computer-use-agents">Documentation</a></b>
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

Add the optional command-line tools with the `cli` extra:

```bash
pip install "hai-agents[cli]"
```

Python 3.10 or newer is required. Get an API key at [portal.hcompany.ai](https://portal.hcompany.ai) and export it:

```bash
export HAI_API_KEY=hk-...
```

## Quickstart

Launch the built-in `h/web-surfer-pro` agent, which ships with its own browser, and describe the task in plain language. `run_session` polls until the agent finishes and returns the final answer.

```python
from hai_agents import Client

client = Client()  # reads HAI_API_KEY from the environment

result = client.run_session(
    agent="h/web-surfer-pro",
    messages="What are the top 3 stories on Hacker News right now?",
)

print(result.status)  # a settled state: "idle" on EU (the default), "completed" on US
print(result.answer)
```

`result` is a `SessionRunResult`: `id`, `status`, `answer`, the accumulated `events`, and `final_changes`.

## How a session works

A session is one run of an agent against a task. It moves through a small set of states: `pending`, `running`, and then a settled state such as `completed`, `idle`, `failed`, `timed_out`, or `interrupted`.

You drive a session two ways. `run_session` creates it and blocks until it settles, which suits one-shot tasks. `start_session` creates it and returns a handle right away, so you can read and steer the agent while it works.

```python
session = client.start_session(
    agent="h/web-surfer-pro",
    messages="Find the top story on Hacker News",
)

print(session.id)
result = session.wait_for_completion()
print(result.status, result.answer)
```

## Watch and steer a running session

A handle bound to the session `id` exposes the full lifecycle. Read the agent's progress at three levels of detail:

```python
session.status()               # cheap snapshot: state, step count, token usage
session.changes(from_index=0)  # new events and the final answer, long-polled
session.get()                  # the full Session resource
```

While the session is not in a terminal state, you can intervene:

```python
session.send_message({"type": "user_message", "message": "Only consider the last 24 hours"})
session.pause()         # halt with state preserved
session.resume()        # continue where it left off
session.force_answer()  # stop exploring and answer from what it has
session.cancel()        # stop for good; ends in "interrupted"
```

`send_message` redirects the agent on its next step. Sending a message to an `idle` session also wakes it.

## Multi-turn sessions

By default a session ends as soon as the agent answers. Set `idle_timeout_s` to keep it open: after each answer the session goes `idle` and waits that long for your next message, carrying its full context and browser state across turns.

```python
session = client.start_session(
    agent="h/web-surfer-pro",
    idle_timeout_s=600,
    messages="Find the top story on Hacker News",
)
first = session.wait_for_completion()

session.send_message({"type": "user_message", "message": "Now summarize its comments"})
second = session.wait_for_completion()
```

## Structured output

Pass a pydantic model as `answer_schema` and the agent's final answer comes back as a validated instance. The model's JSON schema is sent as the agent's answer format; the raw wire value stays at `result.final_changes.answer`.

```python
from pydantic import BaseModel
from hai_agents import Client

class Job(BaseModel):
    title: str
    company: str

class Jobs(BaseModel):
    jobs: list[Job]

client = Client()
result = client.run_session(
    agent="h/web-surfer-pro",
    messages="Find 3 open ML engineering roles in Paris.",
    answer_schema=Jobs,
)

for job in result.answer.jobs:  # result.answer is a Jobs instance
    print(job.title, "@", job.company)
```

A completed answer that does not match the schema raises `AnswerValidationError`, with the raw payload on `.raw`. Sessions that end without completing return their raw answer untouched.

## Custom tools

Expose your own Python functions to the agent. Pass them to `run_session` and the polling loop runs each one when the agent calls it, then posts the result back so the session continues. Any function with typed parameters and a docstring works; the input schema is derived from the signature.

```python
from hai_agents import Client

def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"Sunny in {city}"

client = Client()

result = client.run_session(
    agent="h/web-surfer-pro",
    messages="What should I wear in Paris today?",
    tools=[get_weather],
)
```

Use the `@tool` decorator to override the name or description:

```python
from hai_agents import tool

@tool(name="lookup_order", description="Look up an order by its id.")
def lookup(order_id: str) -> dict:
    return {"id": order_id, "status": "shipped"}
```

A tool that raises is reported to the agent as a tool error rather than crashing the run. With `AsyncClient`, tools may be `async def`.

## Browser profiles and vaults

Start a session on a browser that already knows the user. A [browser profile](https://hub.hcompany.ai/computer-use-agents/browser-profiles) restores saved cookies and storage from an earlier session, and a [vault](https://hub.hcompany.ai/computer-use-agents/vaults) lets the agent sign in to sites with secrets that never enter its context. Bind both through per-run overrides:

```python
result = client.run_session(
    agent="h/web-surfer-pro",
    messages="Open my dashboard and report any new alerts",
    overrides={
        "agent.environments[kind=web].browser_profile_id": "<profile-id>",
        "agent.environments[kind=web].vault_id": "<vault-id>",
    },
)
```

## Async

`AsyncClient` mirrors `Client` for asyncio. Every session method is a coroutine.

```python
import asyncio
from hai_agents import AsyncClient

async def main():
    client = AsyncClient()
    result = await client.run_session(
        agent="h/web-surfer-pro",
        messages="What are the top 3 stories on Hacker News right now?",
    )
    print(result.answer)

asyncio.run(main())
```

## Inspect and share sessions

List past sessions and create a public replay link:

```python
page = client.sessions.list_sessions(size=10)
for summary in page.items:
    print(summary.id, summary.status)

link = client.sessions.share_session("<session-id>")
print(link.share_url)
```

## Regions and configuration

The client targets the EU region by default. Point it at the US region or a custom URL, and override the API key in code when you do not want to use the environment variable:

```python
from hai_agents import Client, HaiAgentsEnvironment

client = Client(environment=HaiAgentsEnvironment.US)
# or
client = Client(base_url="https://agp.hcompany.ai", api_key="hk-...")
```

## Errors

```python
from hai_agents import AnswerValidationError, UnprocessableEntityError
from hai_agents.core import ApiError
```

`ApiError` is the base for HTTP failures and carries `.status_code` and `.body`. `UnprocessableEntityError` is the 422 raised when a request fails validation. `AnswerValidationError` is raised when a completed answer does not match `answer_schema`, with the unparsed value on `.raw`.

## Webhooks

Verify the signature on an incoming webhook before trusting it:

```python
from hai_agents import verify_webhook, WebhookVerificationError

event = verify_webhook(request_body, signature, timestamp, secret)
print(event.type, event.data)
```

## Command line

The `cli` extra installs the `hai` command for driving agents from your terminal:

```bash
hai login                 # browser sign-in, stores a key in ~/.config/hai/.env
hai run "What's the top story on Hacker News?"
hai sessions list
hai sessions watch <session-id>
hai mcp install           # add the hai-agents MCP server to Cursor, VS Code, Claude Code, ...
```

Credentials resolve from `--api-key`, then `HAI_API_KEY`, then a local `.env`. Run `hai --help` for the full command set.

## Documentation

Guides, core concepts, and the full API reference live at **[hub.hcompany.ai/computer-use-agents](https://hub.hcompany.ai/computer-use-agents)**.

## License

[MIT](LICENSE)
