import functools
import json
from collections.abc import Awaitable, Callable
from typing import Any

import click
from click.core import ParameterSource
from surfsky import BrowserTimeoutError, SurfskyError

from .. import session, snapshot
from ..config import Settings
from ..out import emit, output_options, pass_settings, render, run, wait_options
from .scrape import with_scheme

Action = Callable[[session.Attached], Awaitable[Any]]


def save_to_meta(ctx: click.Context, param: click.Parameter, value: Any) -> None:
    ctx.meta[f"surfsky.snapshot.{param.name}"] = value


def snapshot_option(f: Any) -> Any:
    """-s, with the -i and --limit of `snapshot`, which navigation() reads from the context."""

    @functools.wraps(f)
    def command(*args: Any, want_snapshot: bool, **kwargs: Any) -> Any:
        ctx = click.get_current_context()
        limited = ctx.get_parameter_source("limit") is not ParameterSource.DEFAULT
        if not want_snapshot and (limited or ctx.meta["surfsky.snapshot.interactive"]):
            raise click.UsageError("-i and --limit shape the snapshot: add -s")
        return f(*args, want_snapshot=want_snapshot, **kwargs)

    decorated: Any = command
    for option in (
        click.option(
            "--limit",
            type=int,
            default=snapshot.DEFAULT_LIMIT,
            show_default=True,
            expose_value=False,
            callback=save_to_meta,
            help="With -s: maximum elements.",
        ),
        click.option(
            "-i",
            "--interactive",
            is_flag=True,
            expose_value=False,
            callback=save_to_meta,
            help="With -s: only elements you can act on (no headings).",
        ),
        click.option(
            "-s",
            "--snapshot",
            "want_snapshot",
            is_flag=True,
            help="Append the page snapshot after the action.",
        ),
    ):
        decorated = option(decorated)
    return decorated


solve_option = click.option(
    "--no-solve",
    "solve",
    flag_value=False,
    default=True,
    help="Never solve a captcha, so nothing is billed; a challenge page still gets "
    "time to pass by itself. By default challenge pages are solved, which can cost "
    "money on pay-as-you-go.",
)


async def where(page: Any) -> dict[str, Any]:
    return {"url": await page.url(), "title": await page.title()}


def act(
    settings: Settings,
    action: Action,
    *,
    text: Callable[[Any], str] | None = None,
    readonly: bool = False,
    **out: Any,
) -> None:
    async def go() -> Any:
        async with session.attached(settings, readonly=readonly) as a:
            result = await action(a)
            if a.dialogs and isinstance(result, dict):
                result = {**result, "dialogs": a.dialogs}
            return result

    result = run(go())
    if isinstance(result, dict) and result.get("dialogs") and not out.get("json_mode"):
        for dialog in result["dialogs"]:
            verdict = "accepted" if dialog["accepted"] else "dismissed"
            message = json.dumps(dialog["message"], ensure_ascii=False)
            click.echo(f"dialog: {dialog['kind']} {message} {verdict}", err=True)
        result = {key: value for key, value in result.items() if key != "dialogs"}
    emit(result, text=text(result) if text else None, **out)


async def navigation(
    a: session.Attached,
    do: Callable[[], Awaitable[Any]],
    *,
    want_snapshot: bool = False,
    status: bool = False,
    wait: bool = False,
    wait_until: str | None = None,
    solve: bool = True,
) -> dict[str, Any]:
    """Run `do` and report where the page is after it; `wait_until` marks a page navigation."""
    before = await a.page.url()
    snapshot.watch(a.page)
    notes: list[str | None] = []
    challenge: dict[str, Any] = {}
    if wait_until is None:
        await do()
    else:
        try:
            await do()
        except BrowserTimeoutError:
            if await a.page.url() == before:
                raise
            notes.append(
                f"navigation did not reach '{wait_until}'; the page may be partly loaded"
            )
        try:
            outcome = await a.page.pass_challenge(solve=solve)
        except SurfskyError:
            notes.append(
                "challenge check failed: the page may be a challenge page, check 'get title'"
            )
        else:
            if outcome.status != "none":
                challenge["challenge"] = outcome.status.replace("_", " ")
            if outcome.status == "not_solved" and outcome.reason:
                challenge["reason"] = outcome.reason
            if outcome.cost_usd:
                challenge["billed_usd"] = round(outcome.cost_usd, 6)
            if outcome.status == "blocked":
                notes.append(
                    "the site refused this browser: start a new session with "
                    "another --os or proxy"
                )
            if outcome.reason == "load_timeout" and not notes:
                notes.append("the page may be partly loaded")
    data = None
    if want_snapshot:
        meta = click.get_current_context().meta
        data = await snapshot.after_action(
            a.page,
            limit=meta["surfsky.snapshot.limit"],
            interactive=meta["surfsky.snapshot.interactive"],
        )
        notes.append(data.pop("note", None))
    elif wait:
        await snapshot.wait_for_load(a.page)
    result = await where(a.page)
    result["navigated"] = result["url"] != before
    if status:
        result["status"] = a.page.status
    result.update(challenge)
    if note := "; ".join(filter(None, notes)):
        result["note"] = note
    if data is not None:
        snapshot.save_refs(a.state, a.page.target_id, result["url"], data)
        result["snapshot"] = data
    return result


def result_text(result: dict[str, Any]) -> str:
    snap = result.get("snapshot")
    head = render({key: value for key, value in result.items() if key != "snapshot"})
    return head if snap is None else f"{head}\n{snapshot.render_items(snap)}"


@click.command()
@click.argument("url")
@wait_options
@snapshot_option
@solve_option
@output_options
@pass_settings
def goto(
    settings: Settings,
    url: str,
    wait_until: str,
    timeout: float,
    want_snapshot: bool,
    solve: bool,
    **out: Any,
) -> None:
    """Open URL in the active tab; defaults to https://."""
    target = with_scheme(url)

    async def action(a: session.Attached) -> Any:
        async def do() -> None:
            await a.page.goto(target, wait_until=wait_until, timeout=timeout)

        return await navigation(
            a,
            do,
            want_snapshot=want_snapshot,
            status=True,
            wait_until=wait_until,
            solve=solve,
        )

    act(settings, action, text=result_text, **out)


async def history(
    a: session.Attached,
    delta: int,
    wait_until: str,
    timeout: float,
    want_snapshot: bool,
    solve: bool,
) -> dict[str, Any]:
    async def step() -> None:
        if delta < 0:
            moved = await a.page.go_back(timeout=timeout)
        else:
            moved = await a.page.go_forward(timeout=timeout)
        if moved is None:
            raise ValueError("no further history")
        # the SDK's history step returns when the index moves, before the document loads
        await a.page.wait_for_load_state(wait_until, timeout=timeout)

    return await navigation(
        a, step, want_snapshot=want_snapshot, wait_until=wait_until, solve=solve
    )


def history_command(name: str, delta: int, doc: str) -> click.Command:
    @click.command(name, help=doc)
    @wait_options
    @snapshot_option
    @solve_option
    @output_options
    @pass_settings
    def command(
        settings: Settings,
        wait_until: str,
        timeout: float,
        want_snapshot: bool,
        solve: bool,
        **out: Any,
    ) -> None:
        act(
            settings,
            lambda a: history(a, delta, wait_until, timeout, want_snapshot, solve),
            text=result_text,
            **out,
        )

    return command


back = history_command("back", -1, "Go back in history.")
forward = history_command("forward", 1, "Go forward in history.")


@click.command()
@wait_options
@snapshot_option
@solve_option
@output_options
@pass_settings
def reload(
    settings: Settings,
    wait_until: str,
    timeout: float,
    want_snapshot: bool,
    solve: bool,
    **out: Any,
) -> None:
    """Reload the active tab."""

    async def action(a: session.Attached) -> Any:
        async def do() -> None:
            await a.page.reload(wait_until=wait_until, timeout=timeout)

        return await navigation(
            a,
            do,
            want_snapshot=want_snapshot,
            status=True,
            wait_until=wait_until,
            solve=solve,
        )

    act(settings, action, text=result_text, **out)


@click.command("snapshot")
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    help="Only elements you can act on (no headings).",
)
@click.option(
    "--find",
    help="Only elements whose role, name, href or selector contain these words; a|b matches either.",
)
@click.option(
    "--limit",
    type=int,
    default=snapshot.DEFAULT_LIMIT,
    show_default=True,
    help="Maximum elements.",
)
@output_options
@pass_settings
def snapshot_cmd(
    settings: Settings, interactive: bool, find: str | None, limit: int, **out: Any
) -> None:
    """List visible elements as [@ref] role "name" lines.

    Use refs with click or fill. Refs of the same tab and URL are kept; a new URL,
    a tab switch, or -s on an action replaces them. Iframe and shadow contents are
    excluded.
    """

    async def action(a: session.Attached) -> Any:
        data = await snapshot.take(
            a.page, limit=limit, interactive=interactive, find=find
        )
        snapshot.save_refs(
            a.state, a.page.target_id, await a.page.url(), data, merge=True
        )
        return {**await where(a.page), **data}

    act(settings, action, text=snapshot.render, readonly=True, **out)


def short(target_id: str) -> str:
    return target_id[:8]


def find_tab(a: session.Attached, which: str) -> Any:
    """A number from the last `tab list`, or a target id prefix from the live tabs."""
    pages = a.browser.pages
    if which.isdigit():
        order = a.state.get("tabs") or [page.target_id for page in pages]
        index = int(which)
        if index < len(order):
            for page in pages:
                if page.target_id == order[index]:
                    return page
        raise ValueError(f"no tab {which}; see 'surfsky tab list'")
    for page in pages:
        if page.target_id.startswith(which):
            return page
    raise ValueError(f"no tab {which!r}; see 'surfsky tab list'")


@click.group()
def tab() -> None:
    """List, open, switch and close tabs (the cloud allows 5)."""


@tab.command("list")
@output_options
@pass_settings
def tab_list(settings: Settings, **out: Any) -> None:
    """List tab IDs and zero-based numbers for switch and close."""

    async def action(a: session.Attached) -> Any:
        rows = []
        for index, page in enumerate(a.browser.pages):
            rows.append(
                {
                    "index": index,
                    "id": short(page.target_id),
                    "active": page is a.page,
                    **await where(page),
                }
            )
        a.state["tabs"] = [page.target_id for page in a.browser.pages]
        return {"tabs": rows}

    act(
        settings, action, text=lambda result: render(result["tabs"]), readonly=True, **out
    )


@tab.command("new")
@click.argument("url", required=False)
@output_options
@pass_settings
def tab_new(settings: Settings, url: str | None, **out: Any) -> None:
    """Open a tab (optionally at URL) and make it active."""

    async def action(a: session.Attached) -> Any:
        page = await a.browser.new_page()
        if url:
            await page.goto(with_scheme(url))
        a.state["target_id"] = page.target_id
        return {"id": short(page.target_id), **await where(page)}

    act(settings, action, **out)


@tab.command("switch")
@click.argument("which")
@output_options
@pass_settings
def tab_switch(settings: Settings, which: str, **out: Any) -> None:
    """Make tab WHICH (number from `tab list`, or id) the active one."""

    async def action(a: session.Attached) -> Any:
        page = find_tab(a, which)
        await page.bring_to_front()  # a hidden tab's screenshot hangs
        a.state["target_id"] = page.target_id
        return {"id": short(page.target_id), **await where(page)}

    act(settings, action, **out)


@tab.command("close")
@click.argument("which", required=False)
@output_options
@pass_settings
def tab_close(settings: Settings, which: str | None, **out: Any) -> None:
    """Close tab WHICH (default: the active one)."""

    async def action(a: session.Attached) -> Any:
        page = find_tab(a, which) if which else a.page
        if (
            page.target_id == a.browser.target_id
        ):  # the session's own page: close() drops the socket
            await a.browser.cdp.send("Target.closeTarget", {"targetId": page.target_id})
        else:
            await page.close()
        if a.state.get("target_id") == page.target_id:
            a.state["target_id"] = None
        return {"closed": short(page.target_id)}

    act(settings, action, **out)


COMMANDS: list[click.Command] = [goto, back, forward, reload, snapshot_cmd, tab]
