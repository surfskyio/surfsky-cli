import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import click
from surfsky import AsyncSurfsky

from .. import session
from ..config import Settings
from ..out import (
    emit,
    fingerprint_options,
    json_arg,
    output_options,
    pass_settings,
    proxy_options,
    run,
    scalar,
)

Factory = Callable[[AsyncSurfsky], Awaitable[Any]]


def call(
    settings: Settings,
    factory: Factory,
    *,
    text: Callable[[Any], str] | None = None,
    **out: Any,
) -> None:
    async def go() -> Any:
        async with settings.client() as client:
            return await factory(client)

    result = run(go())
    emit(result, text=text(result) if text else None, **out)


@click.group()
def profile() -> None:
    """Save fingerprints, proxies and cookies for reuse across sessions."""


@profile.command("list")
@click.option(
    "--all", "all_", is_flag=True, help="Every profile, not just the first 100."
)
@click.option("--page", type=int, help="Page number, from 0.")
@click.option(
    "--ordering",
    type=click.Choice(["created", "-created", "active", "-active", "title", "-title"]),
)
@output_options
@pass_settings
def profile_list(
    settings: Settings, all_: bool, page: int | None, ordering: str | None, **out: Any
) -> None:
    """List up to 100 profiles; use --all or --page for more."""

    async def factory(client: AsyncSurfsky) -> Any:
        if all_:
            return [
                item
                async for item in client.profiles.iter_all(
                    ordering=ordering or "created"  # ty: ignore[invalid-argument-type]
                )
            ]
        return await client.profiles.list_page(
            page=page,
            page_len=100,
            ordering=ordering,  # ty: ignore[invalid-argument-type]
        )

    call(settings, factory, **out)


@profile.command("get")
@click.argument("uuid")
@output_options
@pass_settings
def profile_get(settings: Settings, uuid: str, **out: Any) -> None:
    """Show a profile's fingerprint, proxy and saved settings."""
    call(settings, lambda client: client.profiles.get(uuid), **out)


@profile.command("create")
@click.argument("title")
@click.option("--description")
@click.option(
    "--cookies", "cookies_json", help="Initial cookies: a JSON array inline, or @file."
)
@fingerprint_options
@proxy_options
@output_options
@pass_settings
def profile_create(
    settings: Settings,
    title: str,
    description: str | None,
    cookies_json: str | None,
    os_: str | None,
    os_version: str | None,
    arch: str | None,
    proxy: str | None,
    country: str | None,
    region: str | None,
    city: str | None,
    proxy_type: str | None,
    **out: Any,
) -> None:
    """Create a profile named TITLE. Needs --os."""
    fingerprint = session.fingerprint_from(os_, os_version, arch)
    if not os_ or fingerprint is None:
        raise click.UsageError("--os is required: win, mac or android")
    proxy_value = session.proxy_from(proxy, country, region, city, proxy_type)
    cookies = json_arg(cookies_json, "--cookies") if cookies_json else None

    async def factory(client: AsyncSurfsky) -> Any:
        return await client.profiles.create(
            title=title,
            fingerprint=fingerprint,
            description=description,
            proxy=proxy_value,
            cookies=cookies,
        )

    call(settings, factory, **out)


@profile.command("update")
@click.argument("uuid")
@click.option("--title")
@click.option("--description")
@proxy_options
@output_options
@pass_settings
def profile_update(
    settings: Settings,
    uuid: str,
    title: str | None,
    description: str | None,
    proxy: str | None,
    country: str | None,
    region: str | None,
    city: str | None,
    proxy_type: str | None,
    **out: Any,
) -> None:
    """Change a profile's title, description or proxy."""
    fields: dict[str, Any] = {}
    if title:
        fields["title"] = title
    if description is not None:
        fields["description"] = description
    if proxy or country:
        fields["proxy"] = session.proxy_from(proxy, country, region, city, proxy_type)
    if not fields:
        raise click.UsageError(
            "nothing to update: give --title, --description or a proxy"
        )
    call(settings, lambda client: client.profiles.update(uuid, **fields), **out)


@profile.command("delete")
@click.argument("uuids", nargs=-1, required=True)
@output_options
@pass_settings
def profile_delete(settings: Settings, uuids: tuple[str, ...], **out: Any) -> None:
    """Delete one or more profiles (running ones are reported, not deleted)."""

    async def factory(client: AsyncSurfsky) -> Any:
        if len(uuids) == 1:
            return await client.profiles.delete(uuids[0])
        return await client.profiles.delete_many(list(uuids))

    call(settings, factory, **out)


@profile.group("cookies")
def profile_cookies() -> None:
    """Export or import a profile's cookies."""


@profile_cookies.command("export")
@click.argument("uuid")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "netscape"]),
    default="json",
    show_default=True,
)
@output_options
@pass_settings
def cookies_export(settings: Settings, uuid: str, fmt: str, **out: Any) -> None:
    """Print a profile's cookies."""
    call(
        settings,
        lambda client: client.profiles.export_cookies(  # ty: ignore[no-matching-overload]
            uuid, export_format=fmt
        ),
        text=scalar,
        **out,
    )


@profile_cookies.command("import")
@click.argument("uuid")
@click.argument("cookies_arg")
@output_options
@pass_settings
def cookies_import(settings: Settings, uuid: str, cookies_arg: str, **out: Any) -> None:
    """Import cookies: a JSON array inline, or @file holding JSON or Netscape text."""
    raw = cookies_arg
    if raw.startswith("@"):
        raw = Path(raw[1:]).read_text(encoding="utf-8")
    try:
        cookies: Any = json.loads(raw)
    except ValueError:
        cookies = raw  # the Netscape format is one text blob

    async def factory(client: AsyncSurfsky) -> Any:
        await client.profiles.import_cookies(uuid, cookies)
        return {"imported": uuid}

    call(settings, factory, **out)


@click.group()
def proxy() -> None:
    """Surfsky's proxy pools: locations and quota."""


@proxy.command("countries")
@click.option("--shared", is_flag=True, help="The shared pool instead of premium.")
@output_options
@pass_settings
def proxy_countries(settings: Settings, shared: bool, **out: Any) -> None:
    """Countries with proxies."""
    call(
        settings,
        lambda client: (
            client.proxies.shared_countries() if shared else client.proxies.countries()
        ),
        **out,
    )


@proxy.command("regions")
@click.argument("country")
@output_options
@pass_settings
def proxy_regions(settings: Settings, country: str, **out: Any) -> None:
    """Regions of COUNTRY (premium)."""
    call(settings, lambda client: client.proxies.regions(country), **out)


@proxy.command("cities")
@click.argument("country")
@click.argument("region")
@output_options
@pass_settings
def proxy_cities(settings: Settings, country: str, region: str, **out: Any) -> None:
    """Cities of REGION in COUNTRY (premium)."""
    call(settings, lambda client: client.proxies.cities(country, region), **out)


@proxy.command("quota")
@click.option("--shared", is_flag=True)
@output_options
@pass_settings
def proxy_quota(settings: Settings, shared: bool, **out: Any) -> None:
    """Show remaining premium proxy traffic; --shared selects the shared pool."""
    call(
        settings,
        lambda client: (
            client.proxies.shared_quota() if shared else client.proxies.quota()
        ),
        **out,
    )


@click.group()
def extension() -> None:
    """Manage extensions; load one with session start --extension UUID."""


@extension.command("list")
@output_options
@pass_settings
def extension_list(settings: Settings, **out: Any) -> None:
    """Every uploaded extension."""
    call(settings, lambda client: client.extensions.list_all(), **out)


@extension.command("get")
@click.argument("uuid")
@output_options
@pass_settings
def extension_get(settings: Settings, uuid: str, **out: Any) -> None:
    """Show extension details by UUID."""
    call(settings, lambda client: client.extensions.get(uuid), **out)


@extension.command("upload")
@click.argument("zip_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--name", required=True)
@output_options
@pass_settings
def extension_upload(settings: Settings, zip_path: str, name: str, **out: Any) -> None:
    """Upload an extension ZIP (max 100 MB)."""
    call(settings, lambda client: client.extensions.upload(zip_path, name), **out)


@extension.command("rename")
@click.argument("uuid")
@click.argument("name")
@output_options
@pass_settings
def extension_rename(settings: Settings, uuid: str, name: str, **out: Any) -> None:
    """Rename an extension."""
    call(settings, lambda client: client.extensions.update(uuid, name=name), **out)


@extension.command("delete")
@click.argument("uuid")
@output_options
@pass_settings
def extension_delete(settings: Settings, uuid: str, **out: Any) -> None:
    """Delete an extension."""

    async def factory(client: AsyncSurfsky) -> Any:
        await client.extensions.delete(uuid)
        return {"deleted": uuid}

    call(settings, factory, **out)


COMMANDS: list[click.Command] = [profile, proxy, extension]
