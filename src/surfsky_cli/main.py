import difflib
import logging
import sys
from typing import Any

import click

from . import __version__
from .config import Settings
from .out import CliError, classify

SECTIONS: list[tuple[str, list[str]]] = [
    ("Setup and one-shot", ["status", "skill", "scrape"]),
    ("Session", ["session"]),
    ("Navigate", ["goto", "back", "forward", "reload"]),
    ("Read", ["snapshot", "get", "is", "screenshot"]),
    (
        "Act",
        ["click", "fill", "type", "press", "select", "hover", "scroll", "mouse", "wait"],
    ),
    ("Page state", ["tab", "cookies"]),
    ("Advanced", ["eval", "cdp"]),
    ("Account", ["profile", "proxy", "extension"]),
]

EPILOG = """\
Credentials (bash/zsh; values from app.surfsky.io):

\b
  export SURFSKY_API_TOKEN='your-token'
  export SURFSKY_API_BASE_URL='your-base-url'

Scrape once (starts and stops a browser):

\b
  surfsky scrape https://example.com --only-main-content

Keep a browser open:

\b
  surfsky session start
  export SURFSKY_SESSION='returned-session-id'
  surfsky goto https://example.com -s
  surfsky click 'text=More information' -s
  surfsky session stop

Use --session ID to select a browser without setting SURFSKY_SESSION.
Sessions bill until stopped or idle for --idle-timeout seconds.

-s includes a page snapshot; use its refs with click or fill.
--json returns structured results; SURFSKY_JSON=1 makes it the default.
"""

GLOBAL_WITH_VALUE = ("--api-token", "--base-url", "--session")
GLOBAL_FLAGS = ("-v", "--verbose")


def hoist(argv: list[str]) -> list[str]:
    """Global options are accepted anywhere: move them in front of the command."""
    front: list[str] = []
    rest: list[str] = []
    it = iter(argv)
    for arg in it:
        name, has_value, _ = arg.partition("=")
        if arg == "--":
            rest.extend([arg, *it])
        elif arg in GLOBAL_FLAGS or (name in GLOBAL_WITH_VALUE and has_value):
            front.append(arg)
        elif name in GLOBAL_WITH_VALUE and (value := next(it, None)) is not None:
            front.extend([name, value])
        else:
            rest.append(arg)
    return front + rest


def suggest(word: str, paths: list[str]) -> str | None:
    """The closest command path for a typo or a bare subcommand name ('start')."""
    by_last = {path.split()[-1]: path for path in paths}
    if word in by_last:
        return by_last[word]
    close = difflib.get_close_matches(word, list(by_last), n=1, cutoff=0.6)
    return by_last[close[0]] if close else None


class Cli(click.Group):
    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        for title, names in SECTIONS:
            rows = [
                (name, self.commands[name].get_short_help_str(limit=70))
                for name in names
                if name in self.commands
            ]
            if rows:
                with formatter.section(title):
                    formatter.write_dl(rows)

    def paths(self) -> list[str]:
        paths: list[str] = []
        for name, command in self.commands.items():
            paths.append(name)
            if isinstance(command, click.Group):
                paths.extend(f"{name} {sub}" for sub in command.commands)
        return paths

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        return super().parse_args(ctx, hoist(args))

    def resolve_command(self, ctx: click.Context, args: list[str]) -> Any:
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError as exc:
            hint = suggest(args[0], self.paths())
            if hint:
                raise click.UsageError(
                    f"no such command '{args[0]}'; did you mean '{hint}'?", ctx
                ) from exc
            raise

    def invoke(self, ctx: click.Context) -> Any:
        try:
            return super().invoke(ctx)
        except click.exceptions.NoArgsIsHelpError as exc:
            bare = exc.ctx or ctx
            names = ", ".join(getattr(bare.command, "commands", {}))
            raise CliError(
                f"{bare.command_path} needs a subcommand: {names}",
                code="usage",
                exit_code=2,
                hint=f"{bare.command_path} --help",
            ) from exc
        except click.UsageError as exc:
            hint = f"{exc.ctx.command_path} --help" if exc.ctx else "surfsky --help"
            raise CliError(
                exc.format_message(), code="usage", exit_code=2, hint=hint
            ) from exc
        except (
            click.ClickException,
            click.exceptions.Exit,
            click.Abort,
            BrokenPipeError,
        ):
            raise
        except Exception as exc:
            raise classify(exc) from exc


@click.group(cls=Cli, epilog=EPILOG)
@click.option("--api-token", help="API token; overrides $SURFSKY_API_TOKEN.")
@click.option("--base-url", help="API base URL; overrides $SURFSKY_API_BASE_URL.")
@click.option(
    "--session", help="Session ID or unique prefix; overrides $SURFSKY_SESSION."
)
@click.option("-v", "--verbose", is_flag=True, help="SDK debug logs on stderr.")
@click.version_option(__version__, "-V", "--version", prog_name="surfsky")
@click.pass_context
def cli(
    ctx: click.Context,
    api_token: str | None,
    base_url: str | None,
    session: str | None,
    verbose: bool,
) -> None:
    """Surfsky: an advanced antidetect cloud browser built to bypass complex browser challenges."""
    ctx.obj = Settings(api_token=api_token, base_url=base_url, session=session)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")  # ty: ignore[call-non-callable]
    cli(windows_expand_args=False)


from .commands import account, actions, page, scrape  # noqa: E402
from .commands import session as session_cmd  # noqa: E402
from .commands import status as status_cmd  # noqa: E402

for command in (
    *status_cmd.COMMANDS,
    *scrape.COMMANDS,
    *session_cmd.COMMANDS,
    *page.COMMANDS,
    *actions.COMMANDS,
    *account.COMMANDS,
):
    cli.add_command(command)
