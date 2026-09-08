import asyncio
import json
import os
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, get_args

import click
from pydantic import BaseModel
from surfsky import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    BrowserTimeoutError,
    CDPError,
    ConfigurationError,
    MonthlySessionLimitError,
    PremiumTrafficLimitError,
    RateLimitError,
    SharedTrafficLimitError,
    SurfskyError,
)
from surfsky.transport import PLAN_FULL
from surfsky.types import WaitUntil

from .config import Settings

EXIT_ERROR = 1
EXIT_NO_SESSION = 3
EXIT_AUTH = 4
EXIT_TIMEOUT = 5
EXIT_NOT_FOUND = 6
EXIT_QUOTA = 7
RETRYABLE = frozenset({"timeout", "rate_limit", "plan_full", "network"})

pass_settings = click.make_pass_decorator(Settings)


class Hinted(SurfskyError):
    """A CLI-side error that carries its own hint."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


class NoSession(Hinted):
    """No usable browser session for this command."""


class SessionGone(NoSession):
    """The cloud no longer has this session."""


class StaleRef(SurfskyError):
    """A snapshot ref that no longer points at anything."""


class NotFound(Hinted):
    """A target that matches nothing."""


class CliError(click.ClickException):
    code: str
    hint: str | None

    def __init__(
        self,
        message: str,
        *,
        code: str = "error",
        exit_code: int = EXIT_ERROR,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        object.__setattr__(self, "exit_code", exit_code)
        self.hint = hint
        # Click renders errors after leaving the command context.
        self.json_mode = os.environ.get("SURFSKY_JSON") == "1"
        if (ctx := click.get_current_context(silent=True)) is not None:
            self.json_mode = ctx.meta.get("surfsky.json_mode", self.json_mode)

    def show(self, file: Any = None) -> None:
        if self.json_mode:
            error = {
                "code": self.code,
                "message": self.message,
                "hint": self.hint,
                "retryable": self.code in RETRYABLE,
            }
            click.echo(json.dumps({"ok": False, "error": error}, ensure_ascii=False))
            return
        click.echo(f"error [{self.code}]: {self.message}", err=True)
        if self.hint:
            click.echo(f"hint: {self.hint}", err=True)


def classify(exc: BaseException) -> CliError:
    """Map SDK and CLI exceptions to stable error codes and exit statuses."""
    message = str(exc) or type(exc).__name__
    start = "'surfsky session start' prints an id; pass it as --session <uuid> or export SURFSKY_SESSION"
    match exc:
        case SessionGone():
            return CliError(
                message, code="session_gone", exit_code=EXIT_NO_SESSION, hint=start
            )
        case NoSession():
            hint = exc.hint or start
            return CliError(
                message, code="no_session", exit_code=EXIT_NO_SESSION, hint=hint
            )
        case AuthenticationError() | ConfigurationError():
            hint = "export SURFSKY_API_TOKEN and SURFSKY_API_BASE_URL (values at app.surfsky.io)"
            return CliError(message, code="auth", exit_code=EXIT_AUTH, hint=hint)
        case BrowserTimeoutError() | APITimeoutError() | TimeoutError():
            return CliError(message, code="timeout", exit_code=EXIT_TIMEOUT)
        case StaleRef():
            return CliError(
                message,
                code="stale_ref",
                exit_code=EXIT_NOT_FOUND,
                hint="run 'surfsky snapshot'",
            )
        case NotFound():
            return CliError(
                message, code="not_found", exit_code=EXIT_NOT_FOUND, hint=exc.hint
            )
        case (
            SharedTrafficLimitError()
            | PremiumTrafficLimitError()
            | MonthlySessionLimitError()
        ):
            return CliError(message, code="quota", exit_code=EXIT_QUOTA)
        case RateLimitError():
            if exc.code == PLAN_FULL:
                hint = "wait, or stop a session ('surfsky session list')"
                return CliError(
                    message, code="plan_full", exit_code=EXIT_QUOTA, hint=hint
                )
            return CliError(message, code="rate_limit", exit_code=EXIT_QUOTA)
        case APIConnectionError():
            return CliError(message, code="network")
        case APIError():
            return CliError(message, code="api")
        case CDPError():
            if "timeout" in message.lower():
                return CliError(message, code="timeout", exit_code=EXIT_TIMEOUT)
            return CliError(message, code="browser")
        case _:
            return CliError(message)


def set_json(ctx: click.Context, param: click.Parameter, value: bool) -> bool:
    value = value or os.environ.get("SURFSKY_JSON") == "1"
    ctx.meta["surfsky.json_mode"] = value
    return value


def _apply(options: tuple[Any, ...]) -> Callable[[Any], Any]:
    # click lists the last-applied option first, so apply in reverse to keep this order
    def decorator(f: Any) -> Any:
        for option in reversed(options):
            f = option(f)
        return f

    return decorator


output_options = _apply(
    (
        click.option(
            "--json", "json_mode", is_flag=True, callback=set_json, help="Output JSON."
        ),
        click.option(
            "-o",
            "--output",
            type=click.Path(dir_okay=False),
            help="Write the output to this file instead of stdout.",
        ),
        click.option("--pretty", is_flag=True, help="Indent JSON output."),
    )
)

proxy_options = _apply(
    (
        click.option(
            "--proxy",
            help="'premium', 'shared', or your own proxy URL (socks5://user:pass@host:port).",
        ),
        click.option("--country", help="Proxy country code, e.g. us."),
        click.option("--region", help="Proxy region (needs --country)."),
        click.option("--city", help="Proxy city (needs --region)."),
        click.option(
            "--proxy-type",
            type=click.Choice(["residential", "mobile"]),
            help="Choose residential or mobile proxies from the premium pool.",
        ),
    )
)

fingerprint_options = _apply(
    (
        click.option(
            "--os",
            "os_",
            type=click.Choice(["win", "mac", "android"]),
            help="Fingerprint OS (one-time sessions and new profiles).",
        ),
        click.option("--os-version", help="Fingerprint OS version, e.g. 11."),
        click.option(
            "--arch",
            type=click.Choice(["x86", "arm"]),
            help="Fingerprint CPU architecture.",
        ),
    )
)

runtime_options = _apply(
    (
        click.option(
            "--block",
            help="Resource types to block, comma-separated: image,font,media,stylesheet.",
        ),
        click.option(
            "--extension",
            multiple=True,
            help="Extension uuid to load (repeatable, max 5).",
        ),
        click.option(
            "--idle-timeout",
            type=click.IntRange(1, 3600),
            help="Seconds without a command before the cloud stops the session. Sessions you keep default to 300; a one-shot scrape uses the server's short default.",
        ),
    )
)


def session_options(f: Any) -> Any:
    return proxy_options(fingerprint_options(runtime_options(f)))


WAIT_UNTIL = click.Choice(get_args(WaitUntil))


def timeout_option(default: float) -> Any:
    return click.option(
        "--timeout",
        type=float,
        default=default,
        show_default=True,
        help="Seconds to wait.",
    )


wait_options = _apply(
    (
        click.option("--wait-until", type=WAIT_UNTIL, default="load", show_default=True),
        timeout_option(30.0),
    )
)


def plain(value: Any) -> Any:
    """pydantic models, and lists of them, as JSON-ready data."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True, by_alias=True)
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [plain(item) for item in value]
    return value


def scalar(value: Any) -> str:
    """Text form of one value: a str as is, anything else (models included) as JSON."""
    return (
        value if isinstance(value, str) else json.dumps(plain(value), ensure_ascii=False)
    )


def render(data: Any) -> str:
    """Text form: `key: value` lines for a dict; a list of dicts is such blocks, blank-line separated."""
    if isinstance(data, dict):
        return "\n".join(f"{key}: {scalar(value)}" for key, value in data.items())
    if isinstance(data, list) and data and all(isinstance(item, dict) for item in data):
        return "\n\n".join(render(item) for item in data)
    if isinstance(data, list):
        return "\n".join(scalar(item) for item in data)
    return scalar(data)


def envelope(data: Any) -> dict[str, Any]:
    data = plain(data)
    if isinstance(data, dict):
        return {"ok": True, **data}
    if isinstance(data, list):
        return {"ok": True, "items": data, "count": len(data)}
    return {"ok": True, "value": data}


def emit(
    data: Any,
    *,
    json_mode: bool = False,
    output: str | None = None,
    pretty: bool = False,
    text: str | None = None,
) -> None:
    """Print `data` as the JSON envelope, or as `text` (else a rendering of `data`)."""
    if json_mode:
        body = json.dumps(
            envelope(data), indent=2 if pretty else None, ensure_ascii=False
        )
    else:
        body = text if text is not None else render(plain(data))
    write(body, output)


def write(body: str | bytes, output: str | None) -> None:
    if output is None:
        # click.echo supplies the trailing newline.
        click.echo(body.rstrip("\n") if isinstance(body, str) else body)
        return
    path = Path(output)
    if isinstance(body, str):
        body = (body.rstrip("\n") + "\n").encode("utf-8")
    path.write_bytes(body)
    click.echo(f"saved: {path}", err=True)


def json_arg(value: str, what: str = "argument") -> Any:
    """A JSON argument: inline, or `@path` to read it from a file."""
    text = Path(value[1:]).read_text(encoding="utf-8") if value.startswith("@") else value
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ValueError(f"{what} is not valid JSON: {exc}") from exc


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)
