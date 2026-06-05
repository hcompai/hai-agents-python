---
name: hai-agents
description: Run H Company's hosted browser and computer-use agents through the Agent API. Use the run_agent tool when a task needs a real browser on the open web (navigating sites, filling forms, clicking through flows, scraping content that only appears after interaction, or multi-step research a static search cannot answer). Other tools (list_agents, get_session, send_message, cancel_session, share_session) discover agents and inspect or steer a run by session id.
---

# H Agents (Agent API)

These tools call H Company's cloud agents over the Agent API. The credential is read from `HAI_API_KEY` (process env or `~/.config/hai/.env`); if calls fail with an auth error, the user needs to run `hai login`.

## Tools

### `run_agent(task, agent?, max_steps?, max_time_s?) -> {session_id, status, answer}`
The main tool. Creates a session, runs the agent to a terminal state, and returns. Blocking.
- `task` (str, required): the full instruction for the agent. See "Writing the task" below.
- `agent` (str, default `h/web-surfer-holo3-1-35b`): registered agent name. Get others from `list_agents`.
- `max_steps` (int, default `20`): cap on reasoning/action steps before the run stops.
- `max_time_s` (float, default `180.0`): backend wall-clock budget in seconds.
- Returns: `session_id` (use it with the other tools), `status` (terminal state, e.g. completed/failed/cancelled), `answer` (the agent's final text, or null if none).

Raise `max_steps`/`max_time_s` for harder, multi-page tasks; the defaults suit a quick lookup.

### `list_agents(search?, page?, size?) -> page of agent definitions`
Discover available agents. `search` (str, optional) case-insensitively matches name/description; `page` (int, default 1), `size` (int, default 20). Use a returned name as `run_agent`'s `agent`.

### `get_session(session_id) -> session envelope`
Fetch the full state/trajectory of a session by id. Use to inspect what an agent did.

### `send_message(session_id, message) -> {ack: true}`
Add a follow-up user message to an existing session. Use to steer or extend a run instead of starting a fresh one. Note `run_agent` already blocks to completion, so follow-ups are for continuing a finished session or correcting course.

### `cancel_session(session_id) -> {ack: true}`
Stop a session. Use if a run is going the wrong way or is no longer needed.

### `share_session(session_id) -> {share_url}`
Produce a public URL to the session's trajectory. Surface it to the user so they can watch what the agent did.

## When to use run_agent

Use it when the answer lives behind real web interaction: browsing specific sites, comparing live data across pages, filling or submitting forms, navigating multi-step flows, or scraping content that only renders after clicking. Also for open-ended web research where the path isn't known up front and one search query won't do.

Do not use it when a plain web search or your own knowledge already answers the question, when the work is local file/shell/code editing, or when the user wants something written or reasoned about in the conversation rather than fetched from the live web.

## Writing the task

The agent is blind to you. It does not see this conversation, your other tool results, or earlier `run_agent` calls. Everything it needs has to live in the `task` string: the goal, any starting URL or search to run, constraints (read-only vs. submit, how many results, date ranges), and the exact return shape you want (a number, a list, JSON, a short summary). If you want structured output, say so in the task.

Passing the user's message verbatim is usually the wrong reflex: their wording elides what they expect you to carry (which site, which account, what they already told you, what the answer should look like). Fold that context in. But preserve concrete details the user supplied (specific URLs, names, search terms, exact quotes), since the agent grounds on them. Add context; don't reword.

Treat a run as long-running and fallible. The agent returns whatever partial result it has if it exhausts `max_steps`/`max_time_s`, and runs can fail (a site blocks automation, an element isn't found, a login wall). Don't surface a final answer to the user while a run is in flight. On a weak or failed result, tighten the task (exact URL, clearer success criterion) and retry, or raise the budgets, or report the blocker. For anything that mutates real state on a logged-in site (posting, purchasing, deleting), confirm with the user first or reframe the task as observe-and-report.

## Examples

Each shows a casual user message becoming a self-contained `task`.

User: *"what's the cheapest direct flight London to NYC next friday"*

    run_agent
      task: On Google Flights, find the cheapest nonstop economy flight from London (any London airport) to New York City (any NYC airport) departing next Friday. Report airline, price in GBP, and exact departure/arrival times. Read-only; do not book. Return as JSON.
      max_time_s: 300

User: *"summarize what this company does"* (with a URL in the thread)

    run_agent
      task: Open https://example-startup.com, read the homepage, product, and about pages, and summarize in 3 sentences what the company sells, who the customer is, and how it's priced. If pricing isn't public, say so.

User (after you drafted a shortlist): *"which of these are still hiring backend engineers"*

    run_agent
      task: |
        For each company below, open its careers page and report whether it currently lists an open backend/server-side engineering role (yes/no, plus title and location if yes). Return a JSON array keyed by company.

        <the shortlist you just produced>

The last example is load-bearing: you already did the reasoning and hand the agent only the live-web part.
