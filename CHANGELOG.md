# Changelog

All notable changes to `hai-agents` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- An inline `web` environment with `host="user_device"` runs as a `desktop` in `shell` mode on the same id, whose agent drives this machine's Chrome with the `web` CLI. That shell runs `web` commands only and refuses any other. A browser with its own `session_id` keeps it, served with `holo local desktop --shell --session-id <id>`. Its fields other than `id` and `lazy` are ignored, with a warning. The `browser` extra installs the `shell` one.

### Removed

- `hai_agents_local.SeleniumBrowserBridge`, `holo local browser`, and the browser check of `holo doctor`. A named agent or environment holding a browser on this machine fails at session start: pass it inline, or store it as a `desktop` in `shell` mode.

### Fixed

- A local bridge that stops while a command runs now answers that command with an error. The platform applies a session's cancel only once its in-flight command has an answer, so an unanswered one held the cancel, and dropped every message sent to the session, until the command's own timeout.

## [0.1.12]

Baseline public release of the Agents API SDK and `hai` CLI. Earlier
`0.1.x` releases are available on [PyPI](https://pypi.org/project/hai-agents/#history).

[Unreleased]: https://github.com/hcompai/hai-agents-python/compare/v0.1.12...HEAD
[0.1.12]: https://github.com/hcompai/hai-agents-python/releases/tag/v0.1.12
