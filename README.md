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

Install the optional command-line entry point when you want local tools:

```bash
pip install "hai-agents[cli]"
```

Requires Python 3.10 or newer. Grab an API key at [portal.hcompany.ai](https://portal.hcompany.ai) and export it:

```bash
export HAI_API_KEY=hk-...
```

## Quickstart

Launch the built-in `h/web-surfer-holo3-1-35b` agent, which ships with its own browser, and describe the task in plain language. `run_session` polls until the agent finishes and returns the final answer.

```python
from hai_agents import Client, run_session

client = Client()  # reads HAI_API_KEY from the environment

result = run_session(
    client,
    agent="h/web-surfer-holo3-1-35b",
    messages="What are the top 3 stories on Hacker News right now?",
)

print(result.status)  # "completed"
print(result.answer)
```

An `AsyncClient` mirrors this API for asyncio.

## Structured output

Pass a pydantic model as `answer_schema` and the agent's final answer comes back as a validated instance. The model's JSON schema is sent as the agent's `answer_format`; the raw wire value stays at `result.final_changes.answer`.

```python
from pydantic import BaseModel
from hai_agents import Client, run_session

class Job(BaseModel):
    title: str
    company: str

class Jobs(BaseModel):
    jobs: list[Job]

client = Client()
result = run_session(
    client,
    agent="h/web-surfer-holo3-1-35b",
    messages="Find 3 open ML engineering roles in Paris.",
    answer_schema=Jobs,
)

for job in result.answer.jobs:  # result.answer is a Jobs instance
    print(job.title, "@", job.company)
```

A completed answer that does not match the schema raises `AnswerValidationError` (the raw payload is on `.raw`). Sessions that end without completing (cancelled, timed out) return their raw answer untouched.

## Custom tools

Expose your own Python functions to the agent: pass them to `run_session` and the polling loop executes them whenever the agent calls one, posting the result back so the session resumes. Any function with typed parameters and a docstring works; the input schema is derived from the signature.

```python
from hai_agents import Client

def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"Sunny in {city}"

client = Client()

result = client.run_session(
    agent="h/researcher",
    messages="What's the weather in Paris?",
    tools=[get_weather],
)
```

Use `@tool(name=..., description=...)` to override what the model sees. Tool exceptions are reported to the agent as tool errors rather than crashing the loop. With `AsyncClient`, tools may be `async def`. For manual control, `client.start_session(tools=[...])` returns a handle whose `wait_for_completion()` dispatches the same way, and sessions awaiting results report the `awaiting_tool_results` status with the pending calls.

## CLI

The `hai-agents[cli]` extra installs the `hai` command:

```bash
hai login                  # browser sign-in; stores a key in ~/.config/hai/.env
hai run "Summarize the H Agent API quickstart"
hai --json run "Reply with exactly: hello" --max-steps 3 --max-time 60
hai sessions list
hai sessions get <session-id>
hai sessions send <session-id> "continue"
hai sessions cancel <session-id>
hai sessions share <session-id>
hai mcp install            # wire the hai-agents MCP server into every detected editor
hai mcp install list       # see supported clients (Cursor, VS Code, Claude Code, Windsurf)
```

`hai mcp install` adds the remote `hai-agents` MCP server to your local editors and
writes your API key into each client config (in plaintext, so keep them private). On
clients that support agent skills (Cursor, Claude Code) it also symlinks a `SKILL.md`
that teaches the model how to drive the server.

`hai login` opens your browser, mints a per-machine API key, and writes it to
`~/.config/hai/.env`. `hai whoami` shows the resolved endpoint and whether you are
authenticated; `hai logout` removes the stored key.

Credentials resolve from flags, then `HAI_API_KEY` in the environment,
then a local `.env`, then `~/.config/hai/.env`. Use `--base-url` or `HAI_API_BASE_URL`
to target a specific Agent Platform host.

## Documentation

Guides, core concepts, and the full API reference live at **[hub.hcompany.ai/agent-api](https://hub.hcompany.ai/agent-api)**, covering streaming progress, steering a live session, regions, structured output, and error handling.

## License

[MIT](LICENSE)
