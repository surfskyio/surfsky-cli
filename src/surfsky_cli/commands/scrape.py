import base64
from typing import Any

import click
from surfsky import BrowserSettings, Page

from .. import html, session
from ..config import Settings
from ..out import (
    emit,
    output_options,
    pass_settings,
    run,
    session_options,
    wait_options,
    write,
)

FORMATS = ("markdown", "html", "raw_html", "links", "screenshot")


def with_scheme(url: str) -> str:
    return url if "://" in url else f"https://{url}"


@click.command()
@click.argument("url", required=False)
@click.option(
    "-f",
    "--format",
    "formats",
    default="markdown",
    show_default=True,
    help="Comma-separated: markdown, html, raw_html, links, screenshot. Multiple formats return JSON.",
)
@click.option(
    "--only-main-content",
    is_flag=True,
    help="Drop navigation, headers, footers, asides, forms.",
)
@click.option("--wait-for", help="CSS selector to wait for before reading.")
@wait_options
@click.option(
    "--screenshot", is_flag=True, help="Add a screenshot (viewport, or --full-page)."
)
@click.option(
    "--full-page", is_flag=True, help="Screenshot the whole page, not just the viewport."
)
@click.option("--profile", help="Use a saved profile's cookies and identity.")
@click.option(
    "--keep",
    is_flag=True,
    help="Leave a new browser running and return its session ID.",
)
@session_options
@output_options
@pass_settings
def scrape(
    settings: Settings,
    url: str | None,
    formats: str,
    only_main_content: bool,
    wait_for: str | None,
    wait_until: str,
    screenshot: bool,
    full_page: bool,
    profile: str | None,
    keep: bool,
    timeout: float,
    idle_timeout: int | None,
    json_mode: bool,
    output: str | None,
    pretty: bool,
    **opts: Any,
) -> None:
    """Read URL as markdown; use --format for HTML, links or screenshots.

    Uses the selected session, or starts and stops a browser. Without URL,
    reads the selected session's current page. Use -f screenshot -o file.png
    to save PNG bytes; screenshots in JSON are base64.
    """
    if keep and settings.session_ref():
        raise click.UsageError(
            "--keep starts a new session, --session reuses one; not both"
        )
    if settings.session_ref() and (profile or idle_timeout or any(opts.values())):
        raise click.UsageError(
            "--session reuses a running browser: drop --profile, --idle-timeout and the "
            "proxy/fingerprint/--block flags"
        )
    wanted = session.split(formats)
    if unknown := [name for name in wanted if name not in FORMATS]:
        raise click.BadParameter(
            f"unknown format {unknown}; choose from {', '.join(FORMATS)}",
            param_hint="--format",
        )
    if (screenshot or full_page) and "screenshot" not in wanted:
        wanted.append("screenshot")
    data = run(
        fetch(
            settings,
            with_scheme(url) if url else None,
            profile=profile,
            keep=keep,
            idle_timeout=idle_timeout,
            opts=opts,
            wait_until=wait_until,
            wait_for=wait_for,
            timeout=timeout,
            want_shot="screenshot" in wanted,
            full_page=full_page,
        )
    )
    result = build(data, wanted, main_content=only_main_content)
    if len(wanted) == 1 and not json_mode:
        single(result, wanted[0], output)
    else:
        emit(result, json_mode=True, output=output, pretty=pretty)


async def fetch(
    settings: Settings,
    url: str | None,
    *,
    profile: str | None,
    keep: bool,
    idle_timeout: int | None,
    opts: dict[str, Any],
    **how: Any,
) -> dict[str, Any]:
    if url is None or settings.session_ref():
        async with session.attached(settings) as a:
            return await read_page(a.page, url, **how)
    kwargs = session.session_kwargs(opts)
    async with settings.client() as client:
        if keep:
            record = await session.start(
                client,
                profile_uuid=profile,
                idle_timeout=idle_timeout,
                dialogs="dismiss",
                **kwargs,
            )
            async with session.attached(settings, record["internal_uuid"]) as a:
                data = await read_page(a.page, url, **how)
            return {"session": record["internal_uuid"], **data}
        if idle_timeout:  # otherwise the server's own inactivity timeout applies
            kwargs["browser_settings"] = BrowserSettings(
                inactive_kill_timeout=idle_timeout
            )
        # The SDK shields session cleanup from cancellation.
        async with client.browser(profile_uuid=profile, **kwargs) as browser:
            return await read_page(browser, url, **how)


async def read_page(
    page: Page,
    url: str | None,
    *,
    wait_until: Any,
    wait_for: str | None,
    timeout: float,
    want_shot: bool,
    full_page: bool,
) -> dict[str, Any]:
    if url is not None:
        await page.goto(url, wait_until=wait_until, timeout=timeout)
    if wait_for:
        await page.wait_for_selector(wait_for, timeout=timeout)
    data: dict[str, Any] = {
        "url": await page.url(),
        "status": page.status,
        "title": await page.title(),
        "raw_html": await page.content(),
    }
    if want_shot:
        data["screenshot"] = await page.screenshot(full_page=full_page)
    return data


def build(
    data: dict[str, Any], formats: list[str], *, main_content: bool
) -> dict[str, Any]:
    result: dict[str, Any] = {
        **({"session": data["session"]} if "session" in data else {}),
        "url": data["url"],
        "status": data["status"],
        "title": data["title"],
    }
    if {"markdown", "html", "links"} & set(formats):
        soup = html.clean(data["raw_html"], main_content=main_content)
        if "markdown" in formats:
            result["markdown"] = html.to_markdown(soup)
        if "html" in formats:
            result["html"] = str(soup)
        if "links" in formats:
            result["links"] = html.links(soup, data["url"])
    if "raw_html" in formats:
        result["raw_html"] = data["raw_html"]
    if "screenshot" in formats:
        result["screenshot"] = base64.b64encode(data["screenshot"]).decode()
    return result


def single(result: dict[str, Any], fmt: str, output: str | None) -> None:
    if "session" in result:
        click.echo(f"session: {result['session']}", err=True)
    if fmt == "screenshot":
        raw = base64.b64decode(result["screenshot"])
        write(raw if output else result["screenshot"], output)  # a file gets bytes
    elif fmt == "links":
        write("\n".join(result["links"]), output)
    else:
        write(result[fmt], output)


COMMANDS: list[click.Command] = [scrape]
