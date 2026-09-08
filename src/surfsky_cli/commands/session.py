from typing import Any

import click
from surfsky import SurfskyError

from .. import config, session
from ..config import Settings
from ..out import (
    NoSession,
    classify,
    emit,
    output_options,
    pass_settings,
    run,
    session_options,
)


@click.group("session")
def session_group() -> None:
    """Start, stop and list billed browser sessions."""


@session_group.command("start")
@click.option(
    "--profile", help="Start this saved profile instead of a one-time identity."
)
@click.option(
    "--dialogs",
    type=click.Choice(["dismiss", "accept"]),
    default="dismiss",
    show_default=True,
    help="Accept or dismiss JavaScript dialogs.",
)
@session_options
@output_options
@pass_settings
def start(
    settings: Settings,
    profile: str | None,
    dialogs: str,
    idle_timeout: int | None,
    **opts: Any,
) -> None:
    """Start a browser on about:blank and print its session ID.

    Use the ID with --session or SURFSKY_SESSION. Billing ends on session stop
    or after --idle-timeout seconds without a command.
    """
    out = {key: opts.pop(key) for key in ("json_mode", "output", "pretty")}
    if profile and any(opts.get(key) for key in ("os_", "os_version", "arch")):
        raise click.UsageError(
            "--os/--os-version/--arch cannot be combined with --profile; "
            "choose the fingerprint with 'surfsky profile create --os'"
        )
    kwargs = session.session_kwargs(opts)

    async def go() -> dict[str, Any]:
        async with settings.client() as client:
            record = await session.start(
                client,
                profile_uuid=profile,
                idle_timeout=idle_timeout,
                dialogs=dialogs,
                **kwargs,
            )
            others = await session.others_running(client, record["internal_uuid"])
        if others:
            plural = "s" if others > 1 else ""
            click.echo(
                f"note: {others} other session{plural} running (surfsky session list)",
                err=True,
            )
        return {
            "session": record["internal_uuid"],
            "idle_timeout": record["idle_timeout"],
            **session.urls(record),
        }

    emit(run(go()), **out)


@session_group.command("stop")
@click.option(
    "--all", "all_", is_flag=True, help="Every session started from this machine."
)
@click.option(
    "--account",
    is_flag=True,
    help="With --all: every session on the account, any machine.",
)
@click.option("--yes", is_flag=True, help="Skip the confirmation for --account.")
@output_options
@pass_settings
def stop(settings: Settings, all_: bool, account: bool, yes: bool, **out: Any) -> None:
    """Stop billing for the selected session; safe to repeat. Use --all for local sessions."""
    if account and not all_:
        raise click.UsageError("--account goes with --all")
    uuid = settings.session_id()
    if not all_ and not uuid:
        raise click.UsageError("pass --session <uuid>, set SURFSKY_SESSION, or use --all")
    if account and not yes:
        click.confirm(
            "Stop every session on the account, including other machines?",
            abort=True,
            err=True,
        )

    async def go() -> dict[str, Any]:
        async with settings.client() as client:
            if all_ and account:
                result = await client.profiles.stop_all()
                actually_stopped = set(result.stopped)
                for record in config.list_sessions():
                    if record["internal_uuid"] in actually_stopped:
                        config.delete_session(record["internal_uuid"])
                return {"stopped": result.stopped, "failed": result.failed}
            if all_:
                stopped: list[str] = []
                failed: list[dict[str, str]] = []
                for record in config.list_sessions():
                    one = record["internal_uuid"]
                    try:
                        await session.stop(client, one)
                        stopped.append(one)
                    except (SurfskyError, TimeoutError) as exc:
                        failed.append({"session": one, "error": str(exc)})
                return {"stopped": stopped, "failed": failed}
            assert uuid is not None
            try:
                await session.stop(client, uuid)
            except (SurfskyError, TimeoutError) as exc:
                error = classify(exc)
                error.hint = f"session {uuid} may keep billing; retry, or 'surfsky session stop --all'"
                raise error from exc
            return {"stopped": True, "session": uuid}

    emit(run(go()), **out)


@session_group.command("list")
@output_options
@pass_settings
def list_cmd(settings: Settings, **out: Any) -> None:
    """Active sessions on the account, with their age."""
    local = {record["internal_uuid"] for record in config.list_sessions()}

    async def go() -> list[dict[str, Any]]:
        async with settings.client() as client:
            active = await client.profiles.list_active()
        alive = {item.internal_uuid for item in active}
        for uuid in local - alive:
            config.delete_session(uuid)
        rows = []
        for item in active:
            row: dict[str, Any] = {"session": item.internal_uuid}
            if item.profile_uuid and not item.one_time:
                row["profile"] = item.profile_uuid
            row["started_at"] = item.started_at
            row["active_seconds"] = item.active_seconds
            rows.append(row)
        return rows

    emit(run(go()), **out)


@session_group.command("devtools")
@output_options
@pass_settings
def devtools(settings: Settings, **out: Any) -> None:
    """Print live view and DevTools URLs for the selected session."""
    uuid = settings.session_id()
    record = config.load_session(uuid) if uuid else None
    if record is None:
        raise NoSession(
            "no session given: pass --session <uuid> or export SURFSKY_SESSION"
        )
    urls = session.urls(record)
    if not urls:
        raise ValueError("this session has no inspector URLs")
    emit(urls, **out)


COMMANDS: list[click.Command] = [session_group]
