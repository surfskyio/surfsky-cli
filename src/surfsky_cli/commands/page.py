import json
from collections.abc import Awaitable, Callable
from typing import Any

import click

from .. import session, snapshot
from ..config import Settings
from ..out import emit, output_options, pass_settings, render, run, wait_options
from .scrape import with_scheme

Action = Callable[[session.Attached], Awaitable[Any]]

snapshot_option = click.option(
    "-s",
    "--snapshot",
    "want_snapshot",
    is_flag=True,
    help="Append the page snapshot after the action.",
)


async def where(page: Any) -> dict[str, Any]:
    return {"url": await page.url(), "title": await page.title()}


def act(
    settings: Settings,
    action: Action,
    *,
    text: Callable[[Any], str] | None = None,
    **out: Any,
) -> None:
    async def go() -> Any:
        async with session.attached(settings) as a:
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
) -> dict[str, Any]:
    """Read the final URL after snapshot settling so navigated reflects the result."""
    before = await a.page.url()
    await do()
    data = await snapshot.after_action(a.page) if want_snapshot else None
    result = await where(a.page)
    result["navigated"] = result["url"] != before
    if status:
        result["status"] = a.page.status
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
@output_options
@pass_settings
def goto(
    settings: Settings,
    url: str,
    wait_until: str,
    timeout: float,
    want_snapshot: bool,
    **out: Any,
) -> None:
    """Open URL in the active tab; defaults to https://."""
    target = with_scheme(url)

    async def action(a: session.Attached) -> Any:
        async def do() -> None:
            await a.page.goto(target, wait_until=wait_until, timeout=timeout)

        return await navigation(a, do, want_snapshot=want_snapshot, status=True)

    act(settings, action, text=result_text, **out)


async def history(
    a: session.Attached, delta: int, wait_until: str, timeout: float, want_snapshot: bool
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

    return await navigation(a, step, want_snapshot=want_snapshot)


def history_command(name: str, delta: int, doc: str) -> click.Command:
    @click.command(name, help=doc)
    @wait_options
    @snapshot_option
    @output_options
    @pass_settings
    def command(
        settings: Settings,
        wait_until: str,
        timeout: float,
        want_snapshot: bool,
        **out: Any,
    ) -> None:
        act(
            settings,
            lambda a: history(a, delta, wait_until, timeout, want_snapshot),
            text=result_text,
            **out,
        )

    return command


back = history_command("back", -1, "Go back in history.")
forward = history_command("forward", 1, "Go forward in history.")


@click.command()
@wait_options
@snapshot_option
@output_options
@pass_settings
def reload(
    settings: Settings, wait_until: str, timeout: float, want_snapshot: bool, **out: Any
) -> None:
    """Reload the active tab."""

    async def action(a: session.Attached) -> Any:
        async def do() -> None:
            await a.page.reload(wait_until=wait_until, timeout=timeout)

        return await navigation(a, do, want_snapshot=want_snapshot, status=True)

    act(settings, action, text=result_text, **out)


@click.command("snapshot")
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    help="Only elements you can act on (no headings).",
)
@click.option(
    "--find", help="Only elements whose role, name, href or selector contain these words."
)
@click.option(
    "--limit", type=int, default=500, show_default=True, help="Maximum elements."
)
@output_options
@pass_settings
def snapshot_cmd(
    settings: Settings, interactive: bool, find: str | None, limit: int, **out: Any
) -> None:
    """List visible elements as [@ref] role "name" lines.

    Use refs with click or fill. Each snapshot replaces saved refs; take a new
    one after navigation or a tab switch. Iframe and shadow contents are excluded.
    """

    async def action(a: session.Attached) -> Any:
        data = await snapshot.take(
            a.page, limit=limit, interactive=interactive, find=find
        )
        snapshot.save_refs(a.state, a.page.target_id, await a.page.url(), data)
        return {**await where(a.page), **data}

    act(settings, action, text=snapshot.render, **out)


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

    act(settings, action, text=lambda result: render(result["tabs"]), **out)


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
