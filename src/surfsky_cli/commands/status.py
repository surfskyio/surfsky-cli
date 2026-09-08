import time
from importlib import resources
from pathlib import Path
from typing import Any

import click
from surfsky import APIError

from .. import __version__, config, session
from ..config import Settings
from ..out import emit, output_options, pass_settings, plain, run


@click.command()
@output_options
@pass_settings
def status(settings: Settings, **out: Any) -> None:
    """Show account limits, proxy quota and selected session status.

    Checking a session reconnects to it and resets its idle timer.
    """
    token, source = settings.token()
    info: dict[str, Any] = {
        "version": __version__,
        "base_url": settings.url(),
        "token_source": source,
    }
    info.update(run(cloud_status(settings)))  # missing credentials exit 4 here
    info.update(run(session_status(settings)))
    emit(info, **out)


async def cloud_status(settings: Settings) -> dict[str, Any]:
    info: dict[str, Any] = {}
    async with settings.client() as client:
        limits = (
            await client.account.browser_limits()
        )  # not guarded: a bad token must fail
        info["parallel_browsers"] = limits.parallel_browsers
        info["running"] = limits.running
        info["available"] = limits.available
        response = await client.request("GET", "/users/plan")
        data = response.json().get("data") if response.status_code < 400 else None
        info["plan"] = (data or {}).get("plan")
        # Optional quota endpoints may be unavailable on this plan.
        for name, call in (
            ("session_limits", client.account.session_limits),
            ("premium_proxy", client.proxies.quota),
            ("shared_proxy", client.proxies.shared_quota),
        ):
            try:
                info[name] = plain(await call())
            except APIError as exc:
                info[name] = f"n/a ({exc.status_code})"
    return info


async def session_status(settings: Settings) -> dict[str, Any]:
    uuid = settings.session_id()
    record = config.load_session(uuid) if uuid else None
    if record is None or uuid is None:
        return {"session": None}
    state = config.load_state(uuid)
    last = state.get("last_used") or record.get("started_at") or time.time()
    info: dict[str, Any] = {
        "session": uuid,
        "profile": record.get("profile_uuid"),
        "idle_timeout": record.get("idle_timeout"),
        "idle_s": int(time.time() - last),
    }
    try:
        async with session.attached(settings) as a:
            info["alive"] = True
            info["url"] = await a.page.url()
            info["title"] = await a.page.title()
            info["tabs"] = len(a.browser.pages)
    except Exception as exc:  # gone or unreachable: status still prints
        info["alive"] = False
        info["error"] = str(exc)
    return info


SKILL_ROOTS = (Path(".claude/skills"), Path(".agents/skills"))


@click.command()
@click.option(
    "--install",
    is_flag=True,
    help="Write SKILL.md into .claude/skills/surfsky-cli and .agents/skills/surfsky-cli.",
)
def skill(install: bool) -> None:
    """Print agent instructions; --install saves them for Claude Code, Codex and Cursor."""
    text = (resources.files("surfsky_cli") / "skill.md").read_text(encoding="utf-8")
    text = text.replace("{version}", __version__)
    if not install:
        click.echo(text, nl=False)
        return
    for root in SKILL_ROOTS:
        path = root / "surfsky-cli/SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        click.echo(f"installed: {path.as_posix()}")


COMMANDS: list[click.Command] = [status, skill]
