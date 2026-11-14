import asyncio
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from click.testing import CliRunner
from surfsky.types import ChallengeResult

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


class FakeCDP:
    def __init__(self):
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler

    def fire(self, event, **params):
        if handler := self.handlers.get(event):
            handler(params, None)


class FakeMouse(Recorder):
    def __init__(self, page):
        super().__init__()
        self._page = page

    async def click(self, x, y, **kwargs):
        self.calls.append(("click", (x, y), kwargs))
        self._page.acted()


class FakeKeyboard(Recorder):
    def __init__(self, page):
        super().__init__()
        self._page = page

    async def press(self, key, **kwargs):
        self.calls.append(("press", (key,), kwargs))
        self._page.acted()

    async def type(self, text):
        self.calls.append(("type", (text,), {}))
        self._page.typed(text)


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
        self.navigates = None
        self.cdp = FakeCDP()
        self.keyboard = FakeKeyboard(self)
        self.mouse = FakeMouse(self)
        self.challenge_result = ChallengeResult(status="none")
        self.field = {"editable": True, "value": "", "focused": True}
        self.focus_steals = 0
        self.focus_misses = 0
        self.check_error = None

    async def url(self):
        return self._url

    async def title(self):
        return self._title

    async def content(self):
        return HTML

    def acted(self):
        if self.after_click_url:
            self._url = self.after_click_url
        if self.navigates:
            (url, seconds), self.navigates = self.navigates, None
            self.cdp.fire("Page.frameStartedLoading", frameId=self.target_id)
            asyncio.get_running_loop().call_later(seconds, self.commit, url)

    def commit(self, url):
        if url is None:
            self.cdp.fire("Page.frameStoppedLoading", frameId=self.target_id)
        else:
            self._url = url
            self.cdp.fire("Page.frameNavigated", frame={"id": self.target_id})

    async def goto(self, url, **kwargs):
        self.calls.append(("goto", (url,), kwargs))
        self._url = url
        self.acted()

    async def wait_for_load_state(self, state, *, timeout=30.0):
        self.calls.append(("wait_for_load_state", (state,), {"timeout": timeout}))

    async def click(self, selector, **kwargs):
        self.calls.append(("click", (selector,), kwargs))
        self.acted()

    def typed(self, text, replace=False):
        if self.field is None or self.field["value"] is None:
            return
        if self.focus_steals:
            self.focus_steals -= 1
            self.field["focused"] = False
            return
        self.field["focused"] = True
        self.field["value"] = text if replace else self.field["value"] + text

    async def fill(self, selector, text, name="fill"):
        self.calls.append((name, (selector, text), {}))
        if self.focus_misses:
            self.focus_misses -= 1
            raise ValueError(f"{selector!r} did not take focus")
        self.typed(text, replace=name == "fill")

    async def type(self, selector, text):
        await self.fill(selector, text, name="type")

    async def evaluate(self, expression, *args, **kwargs):
        self.calls.append(("evaluate", (expression, *args), kwargs))
        if expression.startswith("(selector, mark)"):
            if self.check_error and not args[1]:
                raise self.check_error
            return self.field and dict(self.field)
        if len(args) == 3 and isinstance(args[2], dict):  # the read of one element
            items = [
                item
                for item in self.evaluate_result["items"]
                if item["selector"] == args[2]["selector"]
            ]
            return {"items": items, "total": len(items), "unreachable": []}
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

    async def pass_challenge(self, **kwargs):
        self.calls.append(("pass_challenge", (), kwargs))
        if isinstance(self.challenge_result, Exception):
            raise self.challenge_result
        return self.challenge_result

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
    page = FakePage()
    browser = FakeBrowser(page)
    config.save_session(dict(RECORD))
    config.save_state("S1", dict(STATE))
    monkeypatch.setenv("SURFSKY_SESSION", "S1")

    @asynccontextmanager
    async def attached(settings, uuid=None, *, readonly=False):
        uuid = uuid or settings.session_id()
        record = config.load_session(uuid) if uuid else None
        if record is None:
            raise out.NoSession("no browser session")
        state = config.load_state(uuid)
        a = session.Attached(record, state, browser, page)
        try:
            yield a
        finally:
            state["last_used"] = time.time()
            config.save_state(uuid, state)

    monkeypatch.setattr(session, "attached", attached)
    return SimpleNamespace(page=page, browser=browser)


@pytest.fixture
def invoke():
    runner = CliRunner()

    def call(*args):
        return runner.invoke(cli, list(args))

    return call
