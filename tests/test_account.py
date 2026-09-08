import json
from types import SimpleNamespace

import pytest
from surfsky.types import BatchDeleteResult, ProfileRef, ProfileSummary, ProxyCountry

from surfsky_cli import config


class FakeClient:
    base_url = "https://api.test"

    def __init__(self):
        self.calls = []
        self.profiles = SimpleNamespace(
            list_page=self._list_page,
            create=self._create,
            update=self._update,
            delete=self._delete,
            delete_many=self._delete_many,
            export_cookies=self._export,
        )
        self.proxies = SimpleNamespace(
            countries=self._countries, shared_countries=self._shared
        )
        self.extensions = SimpleNamespace(list_all=self._extensions)

    async def _list_page(self, **kwargs):
        self.calls.append(("list_page", kwargs))
        return [
            ProfileSummary(uuid="p1", title="one"),
            ProfileSummary(uuid="p2", title="two", status="active"),
        ]

    async def _create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return ProfileRef(uuid="new")

    async def _update(self, uuid, **fields):
        self.calls.append(("update", uuid, fields))
        return ProfileRef(uuid=uuid)

    async def _delete(self, uuid):
        return ProfileRef(uuid=uuid)

    async def _delete_many(self, uuids):
        return BatchDeleteResult(deleted_uuids=uuids)

    async def _export(self, uuid, *, export_format):
        return "# Netscape HTTP Cookie File\n" if export_format == "netscape" else []

    async def _countries(self):
        return [ProxyCountry(code="us", name="United States")]

    async def _shared(self):
        return ["us", "de"]

    async def _extensions(self):
        return []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


@pytest.fixture
def client(home, monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(config.Settings, "client", lambda self: fake)
    return fake


def test_profile_list_create_update_delete(client, invoke):
    listing = invoke("profile", "list", "--ordering", "-created")
    assert (
        listing.stdout == "uuid: p1\ntitle: one\n\nuuid: p2\ntitle: two\nstatus: active\n"
    )
    assert client.calls[-1] == (
        "list_page",
        {"page": None, "page_len": 100, "ordering": "-created"},
    )
    created = invoke(
        "profile",
        "create",
        "acct",
        "--os",
        "mac",
        "--proxy",
        "premium",
        "--country",
        "us",
    )
    assert created.stdout == "uuid: new\n"
    kwargs = client.calls[-1][1]
    assert kwargs["title"] == "acct" and kwargs["fingerprint"].os == "mac"
    assert kwargs["proxy"].country == "us" and kwargs["proxy"].tier == "premium"
    assert invoke("profile", "update", "p1", "--title", "renamed").exit_code == 0
    assert client.calls[-1] == ("update", "p1", {"title": "renamed"})
    assert invoke("profile", "update", "p1").exit_code == 2
    assert json.loads(invoke("profile", "delete", "p1", "p2", "--json").stdout)[
        "deleted_uuids"
    ] == ["p1", "p2"]
    assert json.loads(invoke("profile", "delete", "p1", "--json").stdout) == {
        "ok": True,
        "uuid": "p1",
    }


def test_profile_cookies_export(client, invoke):
    assert invoke("profile", "cookies", "export", "p1").stdout == "[]\n"
    assert invoke(
        "profile", "cookies", "export", "p1", "--format", "netscape"
    ).stdout.startswith("# Netscape")


def test_proxy_countries(client, invoke):
    assert invoke("proxy", "countries").stdout == "code: us\nname: United States\n"
    assert invoke("proxy", "countries", "--shared").stdout == "us\nde\n"


def test_extension_list_empty(client, invoke):
    assert json.loads(invoke("extension", "list", "--json").stdout) == {
        "ok": True,
        "items": [],
        "count": 0,
    }
