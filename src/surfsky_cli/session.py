import re
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import urlencode, urlsplit

import anyio
import click
from surfsky import (
    AsyncSurfsky,
    Browser,
    BrowserSettings,
    CDPError,
    Fingerprint,
    NotFoundError,
    PremiumProxy,
    ProxyGeo,
    Session,
    SharedProxy,
    SurfskyError,
)
from surfsky.browser.browser import normalize_blocked

from . import config, snapshot
from .config import Settings
from .out import NoSession, NotFound, SessionGone, StaleRef

POLL = 0.1
TAB_WAIT = 2.0  # pages attach asynchronously after connect
FOCUSED = "@focused"
XPATH = re.compile(r"^(xpath=|//|\(//)")


@dataclass
class Attached:
    session: dict[str, Any]
    state: dict[str, Any]
    browser: Any
    page: Any
    dialogs: list[dict[str, Any]] = field(default_factory=list)


def split(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def proxy_from(
    proxy: str | None,
    country: str | None,
    region: str | None,
    city: str | None,
    proxy_type: str | None,
) -> Any:
    given = {"country": country, "region": region, "city": city, "type": proxy_type}
    targeting = {key: value for key, value in given.items() if value}
    if proxy == "premium":
        return PremiumProxy(**cast(Any, targeting))
    if proxy == "shared":
        return SharedProxy(country=country)
    if proxy:
        if targeting:
            raise click.UsageError(
                "--country/--region/--city/--proxy-type target Surfsky's proxies; "
                "drop them when giving a proxy URL"
            )
        return proxy
    return ProxyGeo(**cast(Any, targeting)) if targeting else None


def fingerprint_from(
    os_: str | None, os_version: str | None, arch: str | None
) -> Fingerprint | None:
    given = {"os": os_, "os_version": os_version, "os_arch": arch}
    fields = {key: value for key, value in given.items() if value}
    return Fingerprint(**cast(Any, fields)) if fields else None


def session_kwargs(opts: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "proxy": proxy_from(
            opts.get("proxy"),
            opts.get("country"),
            opts.get("region"),
            opts.get("city"),
            opts.get("proxy_type"),
        ),
        "fingerprint": fingerprint_from(
            opts.get("os_"), opts.get("os_version"), opts.get("arch")
        ),
        "extensions": list(opts.get("extension") or ()) or None,
        # validated here, before a session is started and billed
        "block_resources": normalize_blocked(set(split(opts.get("block")))) or None,
    }
    return {key: value for key, value in kwargs.items() if value is not None}


def urls(record: dict[str, Any]) -> dict[str, str]:
    inspector = record.get("inspector") or {}
    found: dict[str, str] = {}
    if stream := inspector.get("screencast"):
        query = urlencode({"ws": stream})  # the stream URL carries its own query
        found["screencast"] = f"https://{urlsplit(stream).netloc}/screencast?{query}"
    if inspector.get("list"):
        found["devtools"] = inspector["list"]
    return found


async def others_running(client: AsyncSurfsky, uuid: str) -> int | None:
    # This advisory must not delay or hide a successfully started session.
    try:
        with anyio.fail_after(2):
            active = await client.with_options(
                timeout=2, max_retries=0
            ).profiles.list_active()
        return len({item.internal_uuid for item in active} - {uuid})
    except (SurfskyError, TimeoutError):
        return None


DEFAULT_IDLE_TIMEOUT = 300  # the server's own default is too short for step-by-step work


async def start(
    client: AsyncSurfsky,
    *,
    profile_uuid: str | None,
    idle_timeout: int | None,
    dialogs: str,
    block_resources: frozenset[str] | set[str] | None = None,
    **options: Any,
) -> dict[str, Any]:
    """Save the session before connecting so a failed command can still stop billing."""
    idle_timeout = idle_timeout or DEFAULT_IDLE_TIMEOUT
    options["browser_settings"] = BrowserSettings(inactive_kill_timeout=idle_timeout)
    if profile_uuid:
        session = await client.profiles.start(profile_uuid, **options)
    else:
        session = await client.profiles.start_one_time(**options)
    inspector = session.inspector
    record = {
        "internal_uuid": session.internal_uuid,
        "ws_url": session.ws_url,
        "base_url": client.base_url,
        "profile_uuid": profile_uuid,
        "started_at": time.time(),
        "idle_timeout": idle_timeout,
        "dialogs": dialogs,
        "block_resources": sorted(block_resources or ()),
        "inspector": (
            inspector.model_dump(mode="json", exclude_none=True, by_alias=True)
            if inspector
            else None
        ),
    }
    config.save_session(record)
    config.save_state(session.internal_uuid, {"last_used": time.time()})
    return record


async def stop(client: AsyncSurfsky, uuid: str) -> None:
    """Keep local records until the cloud confirms the session is stopped or missing."""
    fast = client.with_options(timeout=8, max_retries=0)
    try:
        with anyio.fail_after(10):  # total bound; the SDK timeout is per phase
            await fast.profiles.stop(uuid)
    except NotFoundError:
        pass  # already gone
    except TimeoutError as exc:
        raise TimeoutError(f"stopping session {uuid} took more than 10 s") from exc
    config.delete_session(uuid)


def dialog_policy(policy: str, sink: list[dict[str, Any]]) -> Callable[[str, str], bool]:
    def handle(kind: str, message: str) -> bool:
        accepted = kind == "beforeunload" or policy == "accept"
        sink.append({"kind": kind, "message": message, "accepted": accepted})
        return accepted

    return handle


async def clear_dialog(page: Any, policy: str) -> None:
    """A dialog that opened while no command was connected blocks every CDP call."""
    with suppress(CDPError):  # "No dialog is showing": the normal case
        await page.send("Page.handleJavaScriptDialog", {"accept": policy == "accept"})


@asynccontextmanager
async def attached(
    settings: Settings, uuid: str | None = None
) -> AsyncIterator[Attached]:
    """Reconnect to the session for the length of one command."""
    uuid = uuid or settings.session_id()
    if not uuid:
        raise NoSession(
            "no session given: pass --session <uuid> or export SURFSKY_SESSION"
        )
    record = config.load_session(uuid)
    if record is None:
        raise NoSession(
            f"no record of session {uuid!r} on this machine",
            hint="'surfsky session list' shows the account's sessions",
        )
    state = config.load_state(uuid)
    policy = record.get("dialogs") or "dismiss"
    dialogs: list[dict[str, Any]] = []
    browser = Browser(
        Session(internal_uuid=record["internal_uuid"], ws_url=record["ws_url"]),
        block_resources=set(record.get("block_resources") or ()),
    )
    browser.on_dialog = dialog_policy(policy, dialogs)  # survives connect()
    try:
        await browser.connect()
    except Exception as exc:
        await check_alive(settings, record, exc)
        raise
    try:
        page = await pick_tab(browser, state.get("target_id"))
        await clear_dialog(page, policy)
        yield Attached(record, state, browser, page, dialogs)
    finally:
        state["last_used"] = time.time()
        config.save_state(uuid, state)
        await browser.close()


async def check_alive(
    settings: Settings, record: dict[str, Any], cause: Exception
) -> None:
    """Remove local state only when the API confirms the session is gone."""
    try:
        client = settings.client()
        async with client:
            fast = client.with_options(max_retries=0)
            active = {p.internal_uuid for p in await fast.profiles.list_active()}
    except SurfskyError:
        return  # cannot tell; the connect error stands
    uuid = record["internal_uuid"]
    if uuid not in active:
        config.delete_session(uuid)
        raise SessionGone(f"session {uuid} is gone (idle timeout, or stopped)") from cause


async def pick_tab(browser: Any, target_id: str | None) -> Any:
    if not target_id or target_id == browser.target_id:
        return browser
    with anyio.move_on_after(TAB_WAIT):
        while True:
            for page in browser.pages:
                if page.target_id == target_id:
                    return page
            await anyio.sleep(POLL)
    return browser  # the tab is gone; the session's own page is the fallback


def unreachable_hint(count: int) -> str | None:
    if not count:
        return None
    return f"the page has {count} iframe{'s' if count > 1 else ''}/shadow roots the CLI cannot reach"


async def resolve_target(a: Attached, target: str) -> str:
    """Resolve text and snapshot refs to CSS; reject refs from another tab or URL."""
    if XPATH.match(target):
        raise ValueError(
            f"{target!r} looks like XPath; targets are CSS selectors, @refs or text=words"
        )
    if target.startswith("text="):
        words = target[5:]
        found = await snapshot.take(a.page, find=words)
        match = next(
            (
                item
                for item in found["items"]
                if words.lower() in item.get("name", "").lower()
            ),
            None,
        )
        if match is None:
            hint = unreachable_hint(len(found.get("unreachable") or []))
            raise NotFound(f"no element with text {words!r}", hint=hint)
        return match["selector"]
    if not target.startswith("@"):
        return target
    refs = a.state.get("refs") or {}
    if not refs or a.state.get("refs_target_id") != a.page.target_id:
        raise StaleRef("no refs for this tab (another tab, or no snapshot yet)")
    url = await a.page.url()
    if a.state.get("refs_url") != url:
        raise StaleRef(f"refs are from {a.state.get('refs_url')}, the page is now {url}")
    selector = refs.get(target[1:])
    if selector is None:
        raise StaleRef(f"unknown ref {target}")
    if await a.page.count(selector) == 0:
        raise StaleRef(f"{target} ({selector}) is no longer on the page")
    return selector
