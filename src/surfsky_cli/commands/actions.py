import json
import random
import time
from pathlib import Path
from typing import Any

import anyio
import click

from .. import session
from ..config import Settings
from ..out import (
    NotFound,
    emit,
    json_arg,
    output_options,
    pass_settings,
    run,
    scalar,
    set_json,
    timeout_option,
)
from .page import act, navigation, result_text, snapshot_option, where

ELEMENT_TIMEOUT = 10.0
GONE = "s => { const el = document.querySelector(s); return !el || !el.getClientRects().length; }"
OBSERVABLE = ("Runtime.enable", "Console.enable", "Overlay.", "Emulation.")


def modifiers_of(value: str | None) -> Any:
    return session.split(value) or None


def not_found(a: session.Attached, target: str) -> NotFound:
    hint = session.unreachable_hint(a.state.get("unreachable") or 0)
    return NotFound(f"nothing matches {target!r}", hint=hint)


@click.command("click")
@click.argument("target")
@click.option("--button", type=click.Choice(["left", "right", "middle"]))
@click.option("--double", is_flag=True, help="Double-click.")
@click.option("--modifiers", help="Comma-separated: Alt,Control,Meta,Shift.")
@timeout_option(ELEMENT_TIMEOUT)
@snapshot_option
@output_options
@pass_settings
def click_cmd(
    settings: Settings,
    target: str,
    button: str | None,
    double: bool,
    modifiers: str | None,
    timeout: float,
    want_snapshot: bool,
    **out: Any,
) -> None:
    """Click a CSS selector, @ref or text=words target."""

    async def action(a: session.Attached) -> Any:
        selector = await session.resolve_target(a, target)
        method: Any = a.page.dblclick if double else a.page.click

        async def do() -> None:
            await method(
                selector,
                button=button,
                modifiers=modifiers_of(modifiers),
                timeout=timeout,
            )

        return await navigation(a, do, want_snapshot=want_snapshot)

    act(settings, action, text=result_text, **out)


@click.command()
@click.argument("target")
@click.argument("text")
@output_options
@pass_settings
def fill(settings: Settings, target: str, text: str, **out: Any) -> None:
    """Replace an input's text: select all, then type TEXT."""

    async def action(a: session.Attached) -> Any:
        selector = await session.resolve_target(a, target)

        async def do() -> None:
            await a.page.fill(selector, text)

        return await navigation(a, do)

    act(settings, action, text=result_text, **out)


@click.command("type")
@click.argument("target")
@click.argument("text")
@output_options
@pass_settings
def type_cmd(settings: Settings, target: str, text: str, **out: Any) -> None:
    """Click TARGET, then type TEXT after its current text. TARGET @focused skips the click."""

    async def action(a: session.Attached) -> Any:
        async def do() -> None:
            if target == session.FOCUSED:
                await a.page.keyboard.type(text)
            else:
                await a.page.type(await session.resolve_target(a, target), text)

        return await navigation(a, do)

    act(settings, action, text=result_text, **out)


@click.command()
@click.argument("key")
@click.option("--modifiers", help="Comma-separated: Alt,Control,Meta,Shift.")
@snapshot_option
@output_options
@pass_settings
def press(
    settings: Settings, key: str, modifiers: str | None, want_snapshot: bool, **out: Any
) -> None:
    """Press a key on the focused element: Enter, Tab, Escape."""

    async def action(a: session.Attached) -> Any:
        async def do() -> None:
            await a.page.keyboard.press(key, modifiers=modifiers_of(modifiers))

        return await navigation(a, do, want_snapshot=want_snapshot)

    act(settings, action, text=result_text, **out)


@click.command()
@click.argument("target")
@click.argument("value")
@click.option(
    "--label", is_flag=True, help="Match the option's visible label, not its value."
)
@snapshot_option
@output_options
@pass_settings
def select(
    settings: Settings,
    target: str,
    value: str,
    label: bool,
    want_snapshot: bool,
    **out: Any,
) -> None:
    """Pick an <option> of a <select> by value (or by --label)."""

    async def action(a: session.Attached) -> Any:
        selector = await session.resolve_target(a, target)
        picked: dict[str, Any] = {}

        async def do() -> None:
            choice = {"label": value} if label else {"value": value}
            picked["selected"] = await a.page.select_option(selector, **choice)

        return {**await navigation(a, do, want_snapshot=want_snapshot), **picked}

    act(settings, action, text=result_text, **out)


@click.command()
@click.argument("target")
@timeout_option(ELEMENT_TIMEOUT)
@output_options
@pass_settings
def hover(settings: Settings, target: str, timeout: float, **out: Any) -> None:
    """Move the mouse over TARGET."""

    async def action(a: session.Attached) -> Any:
        selector = await session.resolve_target(a, target)

        async def do() -> None:
            await a.page.hover(selector, timeout=timeout)

        return await navigation(a, do)

    act(settings, action, text=result_text, **out)


@click.command()
@click.option(
    "--y",
    type=float,
    help="Pixels down; negative scrolls up (default: most of a screen).",
)
@click.option("--x", type=float, help="Pixels right; negative scrolls left.")
@click.option(
    "--to", "to_target", help="Scroll TARGET (selector, @ref, text=) into view."
)
@click.option("--top", is_flag=True, help="Scroll to the top.")
@click.option("--bottom", is_flag=True, help="Scroll to the bottom.")
@output_options
@pass_settings
def scroll(
    settings: Settings,
    y: float | None,
    x: float | None,
    to_target: str | None,
    top: bool,
    bottom: bool,
    **out: Any,
) -> None:
    """Scroll down most of a screen by default, or use --y PIXELS or --to TARGET."""

    async def action(a: session.Attached) -> Any:
        async def do() -> None:
            if to_target:
                await a.page.scroll_into_view(await session.resolve_target(a, to_target))
            elif top:
                await a.page.scroll_to(y=0)
            elif bottom:
                height = await a.page.evaluate("document.documentElement.scrollHeight")
                await a.page.scroll_to(y=height)
            else:
                delta_y = y
                if y is None and x is None:
                    # A reader paging: most of a screen. Pure CDP, no page JS.
                    metrics = await a.page.send("Page.getLayoutMetrics")
                    height = metrics["cssVisualViewport"]["clientHeight"]
                    delta_y = round(height * random.uniform(0.6, 0.9))
                await a.page.scroll(delta_x=x, delta_y=delta_y)

        return await navigation(a, do)

    act(settings, action, text=result_text, **out)


@click.group()
def mouse() -> None:
    """Pointer input at viewport coordinates for canvases, maps and dragging."""


def pointer_command(name: str, doc: str) -> click.Command:
    @mouse.command(name, help=doc)
    @click.argument("x", type=float)
    @click.argument("y", type=float)
    @output_options
    @pass_settings
    def command(settings: Settings, x: float, y: float, **out: Any) -> None:
        async def action(a: session.Attached) -> Any:
            async def do() -> None:
                await getattr(a.page.mouse, name)(x, y)

            return await navigation(a, do)

        act(settings, action, text=result_text, **out)

    return command


mouse_move = pointer_command("move", "Move the pointer to X, Y.")
mouse_down = pointer_command("down", "Press the left button at X, Y.")
mouse_up = pointer_command("up", "Release the left button at X, Y.")


@mouse.command("click")
@click.argument("x", type=float)
@click.argument("y", type=float)
@click.option("--button", type=click.Choice(["left", "right", "middle"]))
@snapshot_option
@output_options
@pass_settings
def mouse_click(
    settings: Settings,
    x: float,
    y: float,
    button: str | None,
    want_snapshot: bool,
    **out: Any,
) -> None:
    """Click at X, Y."""

    async def action(a: session.Attached) -> Any:
        async def do() -> None:
            await a.page.mouse.click(x, y, button=button)

        return await navigation(a, do, want_snapshot=want_snapshot)

    act(settings, action, text=result_text, **out)


@mouse.command("drag")
@click.argument("x1", type=float)
@click.argument("y1", type=float)
@click.argument("x2", type=float)
@click.argument("y2", type=float)
@output_options
@pass_settings
def mouse_drag(
    settings: Settings, x1: float, y1: float, x2: float, y2: float, **out: Any
) -> None:
    """Drag from X1, Y1 to X2, Y2."""

    async def action(a: session.Attached) -> Any:
        async def do() -> None:
            await a.page.mouse.drag(start_x=x1, start_y=y1, end_x=x2, end_y=y2)

        return await navigation(a, do)

    act(settings, action, text=result_text, **out)


@click.command()
@click.argument("target", required=False)
@click.option(
    "--gone",
    is_flag=True,
    help="Wait until TARGET is removed or has no layout box; use CSS.",
)
@click.option("--url", "fragment", help="Until the URL contains this.")
@click.option(
    "--load",
    type=click.Choice(["load", "domcontentloaded"]),
    help="Until the document reaches this state (networkidle is unobservable after a reconnect).",
)
@click.option("--fn", "expression", help="Until this JavaScript expression is truthy.")
@click.option("--sleep", type=float, help="Wait a fixed number of seconds.")
@timeout_option(30.0)
@output_options
@pass_settings
def wait(
    settings: Settings,
    target: str | None,
    gone: bool,
    fragment: str | None,
    load: str | None,
    expression: str | None,
    sleep: float | None,
    timeout: float,
    **out: Any,
) -> None:
    """Wait for an element, URL, load state or JavaScript condition.

    Prefer CSS for elements that have not appeared yet or may be removed;
    @refs and text=words must resolve before waiting.
    """
    if not any([target, fragment, load, expression, sleep]):
        raise click.UsageError("provide a target, --url, --load, --fn or --sleep")

    async def action(a: session.Attached) -> Any:
        if target:
            selector = await session.resolve_target(a, target)
            if gone:
                await a.page.wait_for_function(GONE, selector, timeout=timeout)
            else:
                await a.page.wait_for_selector(selector, timeout=timeout)
        if fragment:
            await a.page.wait_for_url(fragment, timeout=timeout)
        if load:
            await a.page.wait_for_load_state(load, timeout=timeout)
        if expression:
            await a.page.wait_for_function(expression, timeout=timeout)
        if sleep:
            await anyio.sleep(sleep)
        return await where(a.page)

    act(settings, action, **out)


@click.group()
def get() -> None:
    """Read from the page: url, title, text, html, attr, value, count."""


@get.command("url")
@output_options
@pass_settings
def get_url(settings: Settings, **out: Any) -> None:
    """The active tab's URL."""
    act(settings, lambda a: a.page.url(), text=str, **out)


@get.command("title")
@output_options
@pass_settings
def get_title(settings: Settings, **out: Any) -> None:
    """The active tab's title."""
    act(settings, lambda a: a.page.title(), text=str, **out)


@get.command("text")
@click.argument("target", required=False)
@output_options
@pass_settings
def get_text(settings: Settings, target: str | None, **out: Any) -> None:
    """Rendered text of TARGET (default: the whole page)."""

    async def action(a: session.Attached) -> Any:
        selector = await session.resolve_target(a, target) if target else "body"
        text = await a.page.inner_text(selector)
        if text is None:
            raise not_found(a, target or "body")
        return text

    act(settings, action, text=str, **out)


@get.command("html")
@click.argument("target", required=False)
@output_options
@pass_settings
def get_html(settings: Settings, target: str | None, **out: Any) -> None:
    """Outer HTML of TARGET (default: the whole document)."""

    async def action(a: session.Attached) -> Any:
        if not target:
            return await a.page.content()
        html = await a.page.outer_html(await session.resolve_target(a, target))
        if html is None:
            raise not_found(a, target)
        return html

    act(settings, action, text=str, **out)


@get.command("attr")
@click.argument("target")
@click.argument("name")
@output_options
@pass_settings
def get_attr(settings: Settings, target: str, name: str, **out: Any) -> None:
    """Attribute NAME of TARGET (empty when the element has no such attribute)."""

    async def action(a: session.Attached) -> Any:
        selector = await session.resolve_target(a, target)
        if await a.page.count(selector) == 0:
            raise not_found(a, target)
        return await a.page.get_attribute(selector, name)

    act(settings, action, text=lambda value: value or "", **out)


@get.command("value")
@click.argument("target")
@output_options
@pass_settings
def get_value(settings: Settings, target: str, **out: Any) -> None:
    """Current input, textarea or select value, including edits since page load."""

    async def action(a: session.Attached) -> Any:
        selector = await session.resolve_target(a, target)
        if await a.page.count(selector) == 0:
            raise not_found(a, target)
        return await a.page.evaluate(
            "s => document.querySelector(s)?.value ?? null", selector
        )

    act(settings, action, text=lambda value: "" if value is None else str(value), **out)


@get.command("count")
@click.argument("target")
@output_options
@pass_settings
def get_count(settings: Settings, target: str, **out: Any) -> None:
    """How many elements match TARGET."""

    async def action(a: session.Attached) -> Any:
        return await a.page.count(await session.resolve_target(a, target))

    act(settings, action, text=str, **out)


@click.group("is")
def is_() -> None:
    """Print true or false; both exit 0. Connection or target errors still fail."""


def check(settings: Settings, target: str, key: str, out: dict[str, Any]) -> None:
    async def action(a: session.Attached) -> Any:
        selector = await session.resolve_target(a, target)
        if key == "visible":
            return {key: await a.page.is_visible(selector)}
        return {key: await a.page.count(selector) > 0}

    act(settings, action, text=lambda result: str(result[key]).lower(), **out)


@is_.command("visible")
@click.argument("target")
@output_options
@pass_settings
def is_visible(settings: Settings, target: str, **out: Any) -> None:
    """TARGET exists and has a box on screen."""
    check(settings, target, "visible", out)


@is_.command("present")
@click.argument("target")
@output_options
@pass_settings
def is_present(settings: Settings, target: str, **out: Any) -> None:
    """TARGET exists in the document."""
    check(settings, target, "present", out)


@click.command("screenshot")
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False),
    help="File to write (default: screenshot-<time>.png).",
)
@click.option("--full-page", is_flag=True, help="The whole page, not just the viewport.")
@click.option("--selector", help="Only this element (selector, @ref or text=).")
@click.option("--json", "json_mode", is_flag=True, callback=set_json, help="Output JSON.")
@pass_settings
def screenshot_cmd(
    settings: Settings,
    output: str | None,
    full_page: bool,
    selector: str | None,
    json_mode: bool,
) -> None:
    """Save a PNG of the active tab and print its path."""

    async def go() -> bytes:
        async with session.attached(settings) as a:
            await a.page.bring_to_front()  # a hidden tab's screenshot hangs
            clip = await session.resolve_target(a, selector) if selector else None
            return await a.page.screenshot(selector=clip, full_page=full_page)

    data = run(go())
    path = Path(output or f"screenshot-{int(time.time())}.png")
    path.write_bytes(data)
    emit({"path": str(path), "bytes": len(data)}, json_mode=json_mode, text=str(path))


@click.group()
def cookies() -> None:
    """Read, set or clear cookies in the selected browser."""


@cookies.command("get")
@output_options
@pass_settings
def cookies_get(settings: Settings, **out: Any) -> None:
    """All cookies, as JSON."""
    act(settings, lambda a: a.page.cookies(), text=scalar, **out)


@cookies.command("set")
@click.argument("cookies_json")
@output_options
@pass_settings
def cookies_set(settings: Settings, cookies_json: str, **out: Any) -> None:
    """Set cookies from a JSON array (inline, or @file): what `cookies get` prints."""
    items = json_arg(cookies_json, "cookies")
    if not isinstance(items, list):
        raise ValueError("cookies must be a JSON array")

    async def action(a: session.Attached) -> Any:
        await a.page.set_cookies(items)
        return {"set": len(items)}

    act(settings, action, **out)


@cookies.command("clear")
@output_options
@pass_settings
def cookies_clear(settings: Settings, **out: Any) -> None:
    """Remove all cookies from the selected browser, including logins."""

    async def action(a: session.Attached) -> Any:
        await a.page.clear_cookies()
        return {"cleared": True}

    act(settings, action, **out)


def json_or_text(value: str) -> Any:
    try:
        return json.loads(value)
    except ValueError:
        return value


@click.command("eval")
@click.argument("expression")
@click.argument("args", nargs=-1)
@click.option(
    "--main-world",
    is_flag=True,
    help="Run in the page's own JS context, where its scripts can see it.",
)
@output_options
@pass_settings
def eval_cmd(
    settings: Settings,
    expression: str,
    args: tuple[str, ...],
    main_world: bool,
    **out: Any,
) -> None:
    """Evaluate JavaScript in an isolated context.

    Use --main-world to access page globals.
    Function expressions receive ARGS, parsed as JSON where valid, otherwise strings.
    """

    async def action(a: session.Attached) -> Any:
        values = [json_or_text(value) for value in args]
        return await a.page.evaluate(expression, *values, isolated=not main_world)

    act(settings, action, text=scalar, **out)


@click.command()
@click.argument("method")
@click.argument("params", required=False)
@click.option(
    "--browser", "browser_level", is_flag=True, help="Send at browser level, not the tab."
)
@output_options
@pass_settings
def cdp(
    settings: Settings, method: str, params: str | None, browser_level: bool, **out: Any
) -> None:
    """Send a Chrome DevTools Protocol command.

    Example: surfsky cdp Page.getLayoutMetrics. PARAMS accepts a JSON object.
    """
    if method.startswith(OBSERVABLE):
        click.echo(
            f"warning: {method} is observable by the page and may expose automation",
            err=True,
        )
    payload = json.loads(params) if params else None

    async def action(a: session.Attached) -> Any:
        if browser_level:
            return await a.browser.cdp.send(method, payload)
        return await a.page.send(method, payload)

    act(settings, action, **out)


COMMANDS: list[click.Command] = [
    click_cmd,
    fill,
    type_cmd,
    press,
    select,
    hover,
    scroll,
    mouse,
    wait,
    get,
    is_,
    screenshot_cmd,
    cookies,
    eval_cmd,
    cdp,
]
