"""Command-line interface for the H Agent API SDK."""

_CLI_EXTRAS = {"typer", "rich", "dotenv"}
_CLI_HINT = "The `hai` CLI needs extra dependencies. Install them with: pip install 'hai-agents[cli]'"


def main() -> None:
    """Console-script entry point; fails clearly when the CLI extras are not installed."""
    try:
        from .app import main as _run
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] not in _CLI_EXTRAS:
            raise
        import sys

        print(_CLI_HINT, file=sys.stderr)
        raise SystemExit(1) from None
    _run()
