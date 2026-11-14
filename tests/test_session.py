import asyncio
import json
from types import SimpleNamespace

import click
import pytest
from click.testing import CliRunner
from surfsky import (
    BrowserTimeoutError,
    CDPError,
    NotFoundError,
    PremiumProxy,
    ProxyGeo,
    ServerError,
    SharedProxy,
)

import conftest
from surfsky_cli import config, out, session
from surfsky_cli.main import cli

RECORD = {
    "internal_uuid": "S1",
    "ws_url": "wss://api.test/proxy/S1",
    "idle_timeout": 600,
    "dialogs": "dismiss",
    "block_resources": ["image"],
    "inspector": {
        "list": "https://api.test/proxy/S1/inspector",
        "screencast": "wss://api.test/screencast/S1?token=x",
    },
}
STATE = {
    "target_id": "T2",
    "refs": {"1": "#login"},
    "refs_target_id": "T1",
    "refs_url": "https://e.test/",
}


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SURFSKY_HOME", str(tmp_path))
    monkeypatch.setenv("SURFSKY_API_TOKEN", "t")
    monkeypatch.setenv("SURFSKY_API_BASE_URL", "https://api.test")
    monkeypatch.delenv("SURFSKY_SESSION", raising=False)
    config.save_session(dict(RECORD))
    config.save_state("S1", dict(STATE))
    monkeypatch.setenv("SURFSKY_SESSION", "S1")


def test_proxy_from():
    assert session.proxy_from(None, None, None, None, None) is None
    assert session.proxy_from("premium", "us", None, None, "mobile") == PremiumProxy(
        country="us", type="mobile"
    )
    assert session.proxy_from("shared", "de", None, None, None) == SharedProxy(
        country="de"
    )
    assert session.proxy_from(None, "de", None, None, None) == ProxyGeo(country="de")
    assert (
        session.proxy_from("socks5://u:p@h:1", None, None, None, None)
        == "socks5://u:p@h:1"
    )
    with pytest.raises(click.UsageError, match="proxy URL"):
        session.proxy_from("socks5://h:1", "us", None, None, None)


def test_session_kwargs():
    assert session.session_kwargs({}) == {}
    kwargs = session.session_kwargs(
        {"os_": "win", "os_version": "11", "block": "Image, font", "extension": ("e1",)}
    )
    assert kwargs["fingerprint"].os == "win" and kwargs["fingerprint"].os_version == "11"
    assert kwargs["block_resources"] == frozenset({"image", "font"})
    assert kwargs["extensions"] == ["e1"]
    with pytest.raises(ValueError, match="unknown resource types"):
        session.session_kwargs({"block": "gif"})


def test_urls():
    assert session.urls(RECORD) == {
        "screencast": "https://api.test/screencast?ws=wss%3A%2F%2Fapi.test%2Fscreencast%2FS1%3Ftoken%3Dx",
        "devtools": "https://api.test/proxy/S1/inspector",
    }
    assert session.urls({"inspector": None}) == {}


class FakePage:
    def __init__(self, target_id="T1", url="https://e.test/", counts=None, found=None):
        self.target_id = target_id
        self._url = url
        self.counts = counts or {}
        self.found = found or {"items": [], "total": 0, "unreachable": []}
        self.sent = []

    async def url(self):
        return self._url

    async def count(self, selector):
        return self.counts.get(selector, 0)

    async def evaluate(self, expression, *args, **kwargs):
        return self.found

    async def send(self, method, params=None):
        self.sent.append((method, params))
        return {}


def attached_with(page, state=None):
    return session.Attached(
        dict(RECORD), state if state is not None else dict(STATE), SimpleNamespace(), page
    )


def resolve(a, target):
    return asyncio.run(session.resolve_target(a, target))


def test_resolve_css_and_xpath():
    a = attached_with(FakePage())
    assert resolve(a, "#x") == "#x"
    with pytest.raises(ValueError, match="XPath"):
        resolve(a, "//div")


def test_resolve_ref_checks_tab_url_and_presence():
    good = attached_with(FakePage(target_id="T1", counts={"#login": 1}))
    assert resolve(good, "@1") == "#login"
    with pytest.raises(out.StaleRef, match="another tab|no refs"):
        resolve(attached_with(FakePage(target_id="T9", counts={"#login": 1})), "@1")
    with pytest.raises(out.StaleRef, match="page is now"):
        resolve(
            attached_with(FakePage(url="https://e.test/other", counts={"#login": 1})),
            "@1",
        )
    with pytest.raises(out.StaleRef, match="unknown ref @2"):
        resolve(good, "@2")
    with pytest.raises(out.StaleRef, match="^@1 is no longer on the page$"):
        resolve(attached_with(FakePage(counts={})), "@1")
    with pytest.raises(out.StaleRef, match="^@1 now matches 2 elements$"):
        resolve(attached_with(FakePage(counts={"#login": 2})), "@1")


def test_resolve_text_uses_walker():
    # `find` only narrows the predicate the walker uses (role/href/selector); the
    # fake's evaluate() ignores it entirely, so this also proves the match is made
    # in Python, against `name`, not by trusting whatever items come back.
    found = {
        "items": [
            {
                "ref": 1,
                "role": "link",
                "name": "Results",
                "selector": "a.r",
                "href": "/search-results",
            },
            {"ref": 2, "role": "button", "name": "Search", "selector": "button.s"},
        ],
        "total": 2,
        "unreachable": [],
    }
    assert resolve(attached_with(FakePage(found=found)), "text=search") == "button.s"
    only_link = {
        "items": found["items"][:1],
        "total": 1,
        "unreachable": [{"kind": "iframe"}],
    }
    with pytest.raises(out.NotFound, match="no element with text") as info:
        resolve(attached_with(FakePage(found=only_link)), "text=search")
    assert "1 iframe" in info.value.hint


def test_pick_tab_waits_for_late_attach():
    first, second = SimpleNamespace(target_id="T1"), SimpleNamespace(target_id="T2")

    class Late:
        target_id = "T1"
        polls = 0

        @property
        def pages(self):
            self.polls += 1
            return [first] if self.polls < 3 else [first, second]

    browser = Late()
    assert asyncio.run(session.pick_tab(browser, None)) is browser
    assert asyncio.run(session.pick_tab(browser, "T2")) is second
    assert asyncio.run(session.pick_tab(browser, "T1")) is browser


def test_dialog_policy_and_clear():
    sink = []
    handler = session.dialog_policy("dismiss", sink)
    assert handler("confirm", "sure?") is False and handler("beforeunload", "") is True
    assert sink == [
        {"kind": "confirm", "message": "sure?", "accepted": False},
        {"kind": "beforeunload", "message": "", "accepted": True},
    ]
    assert session.dialog_policy("accept", [])("prompt", "name?") is True
    page = FakePage()
    asyncio.run(session.clear_dialog(page, "accept"))
    assert page.sent == [("Page.handleJavaScriptDialog", {"accept": True})]


class FakeClient:
    base_url = "https://api.test"

    def __init__(self, *, active=(), stop_error=None):
        self.active, self.stop_error, self.stopped = list(active), stop_error, []
        self.profiles = SimpleNamespace(
            list_active=self._list_active,
            stop=self._stop,
            start_one_time=self._start_one_time,
        )

    def with_options(self, **_):
        return self

    async def _list_active(self):
        return [SimpleNamespace(internal_uuid=uuid) for uuid in self.active]

    async def _stop(self, uuid):
        if self.stop_error:
            raise self.stop_error
        self.stopped.append(uuid)

    async def _start_one_time(self, **options):
        self.options = options
        return SimpleNamespace(internal_uuid="S2", ws_url="wss://x/S2", inspector=None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


def test_stop_success_not_found_and_failure():
    client = FakeClient()
    asyncio.run(session.stop(client, "S1"))
    assert (
        client.stopped == ["S1"]
        and config.load_session("S1") is None
        and config.load_state("S1") == {}
    )
    config.save_session(dict(RECORD))
    gone = FakeClient(stop_error=NotFoundError("nope", status_code=404))
    asyncio.run(session.stop(gone, "S1"))
    assert config.load_session("S1") is None
    config.save_session(dict(RECORD))
    broken = FakeClient(stop_error=ServerError("boom", status_code=502))
    with pytest.raises(ServerError):
        asyncio.run(session.stop(broken, "S1"))
    assert config.load_session("S1") is not None


def test_attached_reports_gone_session(monkeypatch):
    class ConnectFails:
        def __init__(self, *args, **kwargs):
            self.on_dialog = None

        async def connect(self):
            raise OSError("connection refused")

        async def close(self):
            return None

    monkeypatch.setattr(session, "Browser", ConnectFails)
    monkeypatch.setattr(config.Settings, "client", lambda self: FakeClient(active=[]))

    async def use():
        async with session.attached(config.Settings()):
            pass

    with pytest.raises(out.SessionGone, match="S1 is gone"):
        asyncio.run(use())
    assert config.load_session("S1") is None

    config.save_session(dict(RECORD))
    monkeypatch.setattr(config.Settings, "client", lambda self: FakeClient(active=["S1"]))
    with pytest.raises(OSError, match="connection refused"):
        asyncio.run(use())
    assert config.load_session("S1") is not None


class DroppingBrowser(conftest.FakePage):
    """Connects, then the socket closes while the SDK call named by `drop` awaits its reply."""

    drop = ""

    def __init__(self, *args, **kwargs):
        super().__init__(target_id="T2")
        self.pages = [self]
        self.connected = True
        setattr(self, self.drop, self.dropped)

    async def dropped(self, *args, **kwargs):
        self.connected = False
        raise CDPError("CDP connection closed")


def run_dropping(monkeypatch, drop, *args):
    monkeypatch.setattr(DroppingBrowser, "drop", drop)
    monkeypatch.setattr(session, "Browser", DroppingBrowser)
    result = CliRunner().invoke(cli, [*args, "--json"])
    return result.exit_code, json.loads(result.stdout)["error"]


@pytest.mark.parametrize(
    ("drop", "args"),
    [
        ("click", ["click", "#go"]),
        ("fill", ["fill", "#q", "x"]),
        ("goto", ["goto", "e.test"]),
        ("evaluate", ["eval", "1"]),
        ("select_option", ["select", "#s", "a"]),
        ("clear_cookies", ["cookies", "clear"]),
    ],
)
def test_drop_after_a_mutating_command_is_outcome_unknown(monkeypatch, drop, args):
    exit_code, error = run_dropping(monkeypatch, drop, *args)
    assert (exit_code, error["code"], error["retryable"]) == (8, "outcome_unknown", False)
    assert "before repeating" in error["hint"]


@pytest.mark.parametrize(
    ("drop", "args"),
    [
        ("title", ["get", "title"]),
        ("evaluate", ["snapshot"]),
        ("count", ["is", "present", "#go"]),
        ("screenshot", ["screenshot"]),
        ("title", ["tab", "list"]),
        ("cookies", ["cookies", "get"]),
        ("wait_for_selector", ["wait", "#go"]),
        ("content", ["scrape"]),
    ],
)
def test_drop_during_a_read_is_network(monkeypatch, drop, args):
    exit_code, error = run_dropping(monkeypatch, drop, *args)
    assert (exit_code, error["code"], error["retryable"]) == (1, "network", True)


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (BrowserTimeoutError("could not connect within 30s"), (5, "timeout", True)),
        (OSError("server rejected WebSocket connection: HTTP 401"), (1, "error", False)),
    ],
)
@pytest.mark.parametrize("args", [["click", "#go"], ["get", "title"]])
def test_a_failed_connect_keeps_its_own_code(monkeypatch, raised, expected, args):
    class ConnectFails(DroppingBrowser):
        async def connect(self):
            raise raised

    monkeypatch.setattr(session, "Browser", ConnectFails)
    monkeypatch.setattr(config.Settings, "client", lambda self: FakeClient(active=["S1"]))
    result = CliRunner().invoke(cli, [*args, "--json"])
    error = json.loads(result.stdout)["error"]
    assert (result.exit_code, error["code"], error["retryable"]) == expected


def test_a_drop_while_resolving_the_target_is_outcome_unknown(monkeypatch):
    config.save_state("S1", {**STATE, "refs_target_id": "T2"})
    exit_code, error = run_dropping(monkeypatch, "count", "click", "@1")
    assert (exit_code, error["code"]) == (8, "outcome_unknown")


def test_a_drop_during_the_challenge_pass_is_reported_by_the_next_call(monkeypatch):
    class Drops(DroppingBrowser):
        drop = "pass_challenge"
        title = DroppingBrowser.dropped

    monkeypatch.setattr(session, "Browser", Drops)
    result = CliRunner().invoke(cli, ["goto", "e.test", "--json"])
    assert json.loads(result.stdout)["error"]["code"] == "outcome_unknown"


def test_error_with_the_connection_up_keeps_its_code(monkeypatch):
    class Fails(DroppingBrowser):
        async def dropped(self, *args, **kwargs):
            raise CDPError("Human.click '#go': bad")

    monkeypatch.setattr(Fails, "drop", "click")
    monkeypatch.setattr(session, "Browser", Fails)
    result = CliRunner().invoke(cli, ["click", "#go", "--json"])
    assert json.loads(result.stdout)["error"]["code"] == "browser"


def test_attached_without_session(monkeypatch):
    monkeypatch.delenv("SURFSKY_SESSION")

    async def use():
        async with session.attached(config.Settings()):
            pass

    with pytest.raises(out.NoSession):
        asyncio.run(use())


def test_start_defaults_idle_timeout(home):
    client = FakeClient()
    record = asyncio.run(
        session.start(client, profile_uuid=None, idle_timeout=None, dialogs="dismiss")
    )
    assert client.options["browser_settings"].inactive_kill_timeout == 300
    assert (
        record["idle_timeout"] == 300 and config.load_session("S2")["idle_timeout"] == 300
    )


def test_start_without_save_writes_no_record(home):
    record = asyncio.run(
        session.start(
            FakeClient(),
            profile_uuid=None,
            idle_timeout=60,
            dialogs="dismiss",
            save=False,
        )
    )
    assert record["internal_uuid"] == "S2" and config.load_session("S2") is None
