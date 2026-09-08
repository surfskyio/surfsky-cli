import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from surfsky_cli import config, out, session
from surfsky_cli.main import cli

HTML = '<html><body><h1>Hi</h1><p>Text <a href="/x">x</a></p></body></html>'

RECORD = {
    "internal_uuid": "S1",
    "ws_url": "wss://api.test/proxy/S1",
    "base_url": "https://api.test",
    "profile_uuid": None,
    "started_at": 0.0,
    "idle_timeout": 600,
    "dialogs": "dismiss",
    "block_resources": [],
    "inspector": {
        "list": "https://api.test/proxy/S1/inspector",
        "screencast": "wss://api.test/screencast/S1?token=x",
    },
}
STATE = {
    "last_used": 0.0,
    "target_id": "T1",
    "refs": {"1": "a.first"},
    "refs_target_id": "T1",
    "refs_url": "https://e.test/",
    "unreachable": 0,
}


class Recorder:
    """Any method not defined below records its call and returns None."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        async def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return None

        return method

    def called(self, name):
        return [call for call in self.calls if call[0] == name]


class FakePage(Recorder):
    def __init__(self, target_id="T1", url="https://e.test/", title="E"):
        super().__init__()
        self.target_id = target_id
        self.status = 200
        self._url = url
        self._title = title
        self.evaluate_result = "ok"
        self.counts = {}
        self.after_click_url = None
        self.url_after_load = None
        self.keyboard = Recorder()
        self.mouse = Recorder()

    async def url(self):
        return self._url

    async def title(self):
        return self._title

    async def content(self):
        return HTML

    async def goto(self, url, **kwargs):
        self.calls.append(("goto", (url,), kwargs))
        self._url = url

    async def wait_for_load_state(self, state, *, timeout=30.0):
        self.calls.append(("wait_for_load_state", (state,), {"timeout": timeout}))
        if self.url_after_load:
            self._url = self.url_after_load

    async def click(self, selector, **kwargs):
        self.calls.append(("click", (selector,), kwargs))
        if self.after_click_url:
            self._url = self.after_click_url

    async def evaluate(self, expression, *args, **kwargs):
        self.calls.append(("evaluate", (expression, *args), kwargs))
        return self.evaluate_result

    async def screenshot(self, **kwargs):
        self.calls.append(("screenshot", (), kwargs))
        return b"\x89PNG-fake"

    async def inner_text(self, selector):
        return f"text of {selector}" if await self.count(selector) else None

    async def outer_html(self, selector):
        return f"<div>{selector}</div>" if await self.count(selector) else None

    async def get_attribute(self, selector, name):
        return f"{name}-of-{selector}" if name != "missing" else None

    async def count(self, selector):
        return self.counts.get(selector, 1)

    async def is_visible(self, selector):
        return selector != "#hidden"

    async def go_back(self, **kwargs):
        self._url = "https://e.test/prev"
        return self._url

    async def go_forward(self, **kwargs):
        return None  # end of history

    async def select_option(self, selector, value=None, *, label=None):
        self.calls.append(("select_option", (selector, value), {"label": label}))
        return value or label

    async def cookies(self):
        return []

    async def send(self, method, params=None):
        self.calls.append(("send", (method, params), {}))
        if method == "Page.getLayoutMetrics":
            return {"cssVisualViewport": {"clientHeight": 1000}}
        return {"method": method}


class FakeBrowser(Recorder):
    def __init__(self, page):
        super().__init__()
        self.pages = [page]
        self.target_id = page.target_id
        self.cdp = Recorder()

    async def new_page(self):
        page = FakePage(target_id=f"T{len(self.pages) + 1}", url="about:blank", title="")
        self.pages.append(page)
        return page


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SURFSKY_HOME", str(tmp_path))
    monkeypatch.setenv("SURFSKY_API_TOKEN", "test-token")
    monkeypatch.setenv("SURFSKY_API_BASE_URL", "https://api.test")
    monkeypatch.delenv("SURFSKY_SESSION", raising=False)
    monkeypatch.delenv("SURFSKY_JSON", raising=False)
    return tmp_path


@pytest.fixture
def fake(home, monkeypatch):
    """Session S1 on disk; `attached()` yields fakes instead of connecting, and persists state."""
    page = FakePage()
    browser = FakeBrowser(page)
    config.save_session(dict(RECORD))
    config.save_state("S1", dict(STATE))
    monkeypatch.setenv("SURFSKY_SESSION", "S1")

    @asynccontextmanager
    async def attached(settings, uuid=None):
        uuid = uuid or settings.session_id()
        record = config.load_session(uuid) if uuid else None
        if record is None:
            raise out.NoSession("no browser session")
        state = config.load_state(uuid)
        a = session.Attached(record, state, browser, page)
        try:
            yield a
        finally:
            state["last_used"] = time.time()  # what the real attached() does on exit
            config.save_state(uuid, state)

    monkeypatch.setattr(session, "attached", attached)
    return SimpleNamespace(page=page, browser=browser)


@pytest.fixture
def invoke():
    runner = CliRunner()

    def call(*args):
        return runner.invoke(cli, list(args))

    return call
