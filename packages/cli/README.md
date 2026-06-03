# hai

Command-line interface for the [H Company](https://hcompany.ai) [Agent API](https://hub.hcompany.ai/agent-api). Launch autonomous agents powered by Holo, stream their progress, and steer them from your terminal.

## Installation

```bash
pip install hai-agents-cli
```

Requires Python 3.10 or newer. Grab an API key at [portal.hcompany.ai](https://portal.hcompany.ai).

## Configure

```bash
export H_API_KEY="YOUR_API_KEY"   # or: hai configure
```

`hai` resolves credentials from flags, then environment (`H_API_KEY`, `H_REGION`, `H_BASE_URL`), then `~/.config/hai/config.toml`.

## Quickstart

```bash
hai session run --agent h/web-surfer-holo3-1-35b \
  --message "What are the top 3 stories on Hacker News right now?"
```

`run` launches the agent, streams its progress to stderr, and prints the final answer to stdout. Tail an existing session with `hai session tail <id>`.

## Output

On a terminal you get tables and styled text; when piped, `hai` emits JSON so it composes with `jq` and scripts:

```bash
hai session list -o json | jq '.items[].id'
```

Data goes to stdout, progress and notes to stderr. Force a format with `--output/-o [auto|json]`.

## Commands

- `hai session` - `run`, `create`, `tail`, `status`, `get`, `list`, `events`, `send`, `pause`, `resume`, `force-answer`, `cancel`, `feedback`, `event-feedback`, `share`, `unshare`, `quota`
- `hai agent` / `hai skill` / `hai env` - `list`, `get`, `create`, `update`, `delete`
- `hai configure` - save credentials

Run `hai --help` or `hai <command> --help` for details.

## Documentation

Full guides, core concepts, and the API reference live at **[hub.hcompany.ai/agent-api](https://hub.hcompany.ai/agent-api)**.

## License

[MIT](LICENSE)
