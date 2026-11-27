# Changelog

All notable changes to `hai-agents` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- A desktop in `shell` mode reaches the MCP servers in `~/.config/hai/mcp.json` (Cursor's `mcpServers` format) with `mcporter` in its shell. Their keys, `${VAR}` filled from the environment or `~/.config/hai/.env`, stay in this process: it serves each server on a loopback port the sandbox opens for it alone, and the sandbox reads neither the file nor the variables it names. A session the client serves names them, never their keys, in its request's `connections`, so the agent knows them from its first step. `holo connections` lists, checks, adds and imports them from Cursor or Claude. The `shell` extra now brings `mcp`.

### Changed

- The `cli` and `shell` extras run on `mcp` 2 (`mcp>=2.2,<3`), so they install beside projects on `mcp` 2. `holo mcp` also reports each step's tool calls and the kill-switch hint as progress messages, for hosts on MCP's 2026-07-28 protocol, which drops logging.
- An inline `web` environment with `host="user_device"` runs as a `desktop` in `shell` mode on the same id, whose agent drives this machine's Chrome with the `web` CLI. That shell runs `web` commands only, refuses any other, and works in `~/hai/<session_id>`. It leaves the screen to other agents and asks for no screen permission. Its fields other than `id` and `lazy` are ignored, with a warning. Install it with `pip install "hai-agents[shell]"`.

### Fixed

- `Client.local()` runs agents, environments and skills given by name, like `agent="h/web-surfer"` or `"environments": ["h/browser"]`. A local runtime has no catalog, so the client fetches each named spec from the platform of `HAI_API_KEY` (and `HAI_API_BASE_URL`) and sends it inline.

### Removed

- The `browser` extra, `hai_agents_local.SeleniumBrowserBridge`, `holo local browser`, and the browser check of `holo doctor`. A named agent or environment holding a browser on this machine fails at session start: pass it inline, or store a `desktop` in `shell` mode, whose shell runs any command. So does one with its own `session_id` or under an override of `environments[kind=web]` or `[kind=desktop]`, since the client serves it, and one beside another shell on this machine, whose desktop drives Chrome with `web` itself.
- The typed `Browser.host` field and the `BrowserHost` and `PatchEnvironmentHost` types. `host` still parses as an untyped field, so `Browser(id="web", host="user_device")` keeps working; code that imports either type does not.

## [0.1.12]

Baseline public release of the Agents API SDK and `hai` CLI. Earlier
`0.1.x` releases are available on [PyPI](https://pypi.org/project/hai-agents/#history).

[Unreleased]: https://github.com/hcompai/hai-agents-python/compare/v0.1.12...HEAD
[0.1.12]: https://github.com/hcompai/hai-agents-python/releases/tag/v0.1.12
