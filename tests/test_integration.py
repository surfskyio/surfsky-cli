"""The real SDK Browser and CDP client over a scripted CDP: reconnect, tab pick, blocking, dialogs."""

import asyncio

import pytest
from surfsky import CDPError

from conftest import RECORD, STATE
from surfsky_cli import config, session


class ScriptedCDP:
    def __init__(self, targets):
        self.connected = True
        self.commands = []
        self.handlers = {}
        self.targets = targets  # target id → url

    def on(self, event, handler):
        self.handlers[event] = handler

    async def start(self):
        return None

    async def stop(self):
        self.connected = False

    async def post(self, method, params=None, session_id=None):
        result = await self.send(method, params, session_id)
        reply = asyncio.get_running_loop().create_future()
        reply.set_result(result)
        return 0, reply

    async def send(self, method, params=None, session_id=None):
        self.commands.append((method, params, session_id))
        match method:
            case "Target.setAutoAttach":
                for target_id, url in self.targets.items():
                    self.handlers["Target.attachedToTarget"](
                        {
                            "sessionId": f"sess-{target_id}",
                            "targetInfo": {
                                "type": "page",
                                "targetId": target_id,
                                "url": url,
                            },
                        },
                        None,
                    )
            case "Target.getTargetInfo":
                target_id = params["targetId"]
                return {"targetInfo": {"title": "T", "url": self.targets[target_id]}}
            case "Page.handleJavaScriptDialog":
                raise CDPError("No dialog is showing")
        return {}


class Registry(list):
    def __init__(self, targets):
        super().__init__()
        self.targets = targets

    def __call__(self, ws, **kwargs):
        client = ScriptedCDP(self.targets)
        self.append(client)
        return client

    @property
    def commands(self):
        return [command for client in self for command in client.commands]


@pytest.fixture
def cdp(monkeypatch):
    registry = Registry({"T1": "https://e.test/", "T2": "https://e.test/two"})
    monkeypatch.setattr("surfsky.browser.browser.CDPClient", registry)
    return registry


def test_reconnect_twice_picks_tab_reapplies_blocking_clears_dialog(
    home, cdp, monkeypatch
):
    config.save_session({**RECORD, "block_resources": ["image"], "dialogs": "accept"})
    config.save_state("S1", {**STATE, "target_id": "T2"})
    monkeypatch.setenv("SURFSKY_SESSION", "S1")

    async def once():
        async with session.attached(config.Settings()) as a:
            return a.page.target_id, len(a.browser.pages), await a.page.url()

    assert asyncio.run(once()) == ("T2", 2, "https://e.test/two")
    assert asyncio.run(once()) == ("T2", 2, "https://e.test/two")
    assert len(cdp) == 2 and all(not client.connected for client in cdp)

    enables = [c for c in cdp.commands if c[0] == "Fetch.enable"]
    assert len(enables) == 4  # two pages, two connections
    assert all(
        {"urlPattern": "*", "resourceType": "Image"} in c[1]["patterns"] for c in enables
    )

    dialogs = [c for c in cdp.commands if c[0] == "Page.handleJavaScriptDialog"]
    assert dialogs == [("Page.handleJavaScriptDialog", {"accept": True}, "sess-T2")] * 2

    assert "Runtime.enable" not in [c[0] for c in cdp.commands]  # the SDK's rule holds
    assert config.load_state("S1")["last_used"] > 0


def test_ref_invalidated_by_navigation(home, cdp, monkeypatch):
    config.save_session(dict(RECORD))
    config.save_state("S1", {**STATE, "refs_url": "https://e.test/old"})
    monkeypatch.setenv("SURFSKY_SESSION", "S1")

    async def resolve():
        async with session.attached(config.Settings()) as a:
            return await session.resolve_target(a, "@1")

    with pytest.raises(session.StaleRef, match="page is now https://e.test/"):
        asyncio.run(resolve())
