# Changelog

All notable changes to `hai-agents` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- An inline `web` environment with `host="user_device"` runs as a `desktop` in `shell` mode on the same id, whose agent drives this machine's Chrome with the `web` CLI. That shell runs `web` commands only, refuses any other, and works in `~/hai/<session_id>`. It leaves the screen to other agents and asks for no screen permission. Its fields other than `id` and `lazy` are ignored, with a warning. Install it with `pip install "hai-agents[shell]"`.

### Removed

- The `browser` extra, `hai_agents_local.SeleniumBrowserBridge`, `holo local browser`, and the browser check of `holo doctor`. A named agent or environment holding a browser on this machine fails at session start: pass it inline, or store a `desktop` in `shell` mode, whose shell runs any command. So does one with its own `session_id` or under an override of `environments[kind=web]` or `[kind=desktop]`, since the client serves it, and one beside another shell on this machine, whose desktop drives Chrome with `web` itself.

## [0.1.12]

Baseline public release of the Agents API SDK and `hai` CLI. Earlier
`0.1.x` releases are available on [PyPI](https://pypi.org/project/hai-agents/#history).

[Unreleased]: https://github.com/hcompai/hai-agents-python/compare/v0.1.12...HEAD
[0.1.12]: https://github.com/hcompai/hai-agents-python/releases/tag/v0.1.12
