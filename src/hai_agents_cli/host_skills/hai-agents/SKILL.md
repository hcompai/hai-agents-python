---
name: hai-agents
description: Delegate a task to an autonomous H Company agent (Holo-powered web surfer and computer-use agents) through the hai-agents MCP server. Use to offload open-ended browser or research work that the agent should carry out end to end on its own infrastructure, then report a final answer. Runs remotely, so it is the right tool when the work is "go do this on the web and come back with the result" rather than something you can answer directly or do with local files.
---

# hai-agents

The `hai-agents` MCP server runs H Company's autonomous agents on H Company's infrastructure and streams back a single answer. You hand an agent a self-contained `task`; it opens its own browse-and-act loop in a remote browser and works until it has an answer, hits its step or time budget, or is cancelled. Nothing runs on the user's machine.

The agent is blind to this conversation. It sees only the `task` string, so fold in the context it needs: which site or source, what "done" looks like, the shape of the answer you want back. Keep the user's own action verbs and any literal text (search queries, message bodies) verbatim, since the agent grounds well on natural imperatives. Paraphrase by adding context, not by rewording.

Use it for open-ended work on the live web: finding and extracting information across pages, filling in and submitting forms, multi-step navigation behind logins the agent can perform, and research that needs a real browser. It is the wrong tool when the answer is already in your knowledge or a single fetch, when the job is local file, shell, or code work, or when the user wants something written or explained in the conversation rather than done on the web.

## Tools

- `list_agents()` — agents the caller can run (their org's plus the public `h/` ones). Pick the `agent` name from here.
- `run_agent(task, agent, max_steps?, max_time_s?, idempotency_key?)` — start a run. Returns either the final answer or a session handle `{ session_id, status, answer, done }`.
- `wait_for_session(session_id, wait=True)` — long-poll a running session for its answer; `wait=False` returns the current snapshot without blocking.
- `send_message(session_id, message)` — steer a running session with a follow-up.
- `cancel_session(session_id)` — stop a run you no longer need.
- `share_session(session_id)` — get a public read-only URL for the run.

## Long-running tasks

MCP clients cap a single tool call at roughly a minute, but agent runs often take longer, so the server long-polls instead of blocking the whole time:

1. Call `run_agent`. It waits up to about 24 seconds, then returns either the final answer or a handle with `done: false`.
2. If `done` is false, call `wait_for_session(session_id)` to keep long-polling.
3. Repeat `wait_for_session` until `done` is true, then surface the answer.

This loop is the whole protocol: a run that finishes fast returns straight from `run_agent`; a long one is just more `wait_for_session` calls. Treat the work as long-running — do not give the user a final answer while a session is still in flight, and if a run fails or times out, refine the `task` with more specifics and retry, or surface the failure.

## Examples

User: *"find the cheapest direct flight from Paris to Lisbon next Friday"*

    run_agent
      agent: h/web-surfer-pro
      task: On Google Flights, find the cheapest direct (non-stop) flight from Paris (any CDG/ORY) to Lisbon (LIS) departing next Friday, returning the airline, departure and arrival times, and total price in EUR.

User: *"is the H Company Agent API quickstart still showing the curl example"*

    run_agent
      agent: h/web-surfer-pro
      task: Open https://hub.hcompany.ai/computer-use-agents/quickstart and confirm whether the quickstart page still shows a curl example. Return yes or no and quote the first line of the example if present.
