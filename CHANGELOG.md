# Changelog

All notable changes to `hai-agents` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- A local bridge that stops while a command runs now answers that command with an error. The platform applies a session's cancel only once its in-flight command has an answer, so an unanswered one held the cancel, and dropped every message sent to the session, until the command's own timeout.
- A bridge whose process died mid-command (crash, force quit) left that command unanswered for good: the platform does not send it to a new bridge. A bridge now records the command it runs under `~/.hai/bridge-commands/`, and the next bridge on the same channel answers a left one with the same error when it starts.

## [0.1.12]

Baseline public release of the Agents API SDK and `hai` CLI. Earlier
`0.1.x` releases are available on [PyPI](https://pypi.org/project/hai-agents/#history).

[Unreleased]: https://github.com/hcompai/hai-agents-python/compare/v0.1.12...HEAD
[0.1.12]: https://github.com/hcompai/hai-agents-python/releases/tag/v0.1.12
