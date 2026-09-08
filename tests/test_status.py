import json
from types import SimpleNamespace

from surfsky.types import BrowserLimits, ProxyQuota, SessionLimits

from surfsky_cli import __version__, config


class FakeClient:
    """Enough of AsyncSurfsky for status."""

    base_url = "https://api.test"

    def __init__(self, *args, **kwargs):
        self.account = SimpleNamespace(
            browser_limits=self._browser_limits, session_limits=self._session_limits
        )
        self.proxies = SimpleNamespace(quota=self._quota, shared_quota=self._quota)

    async def _browser_limits(self):
        return BrowserLimits(parallel_browsers=3, running=1, available=2)

    async def _session_limits(self):
        return SessionLimits(has_session_limits=False)

    async def _quota(self):
        return ProxyQuota(remaining_gb=1.5)

    async def request(self, method, path, **kwargs):
        return SimpleNamespace(status_code=200, json=lambda: {"data": {"plan": "pro"}})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


def test_status_without_auth(home, invoke, monkeypatch):
    monkeypatch.delenv("SURFSKY_API_TOKEN")
    result = invoke("status", "--json")
    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["code"] == "auth"


def test_status_with_cloud_and_session(fake, invoke, monkeypatch):
    monkeypatch.setattr(config.Settings, "client", lambda self: FakeClient())
    data = json.loads(invoke("status", "--json").stdout)
    assert (
        data["token_source"] == "env"
        and data["plan"] == "pro"
        and data["parallel_browsers"] == 3
    )
    assert data["session"] == "S1" and data["alive"] is True
    assert (
        data["tabs"] == 1
        and data["url"] == "https://e.test/"
        and data["idle_timeout"] == 600
    )
    assert data["premium_proxy"] == {"remaining_gb": 1.5}
    assert config.load_state("S1")["last_used"] > 0


def test_missing_token_is_auth_error(home, invoke, monkeypatch):
    monkeypatch.delenv("SURFSKY_API_TOKEN")
    result = invoke("session", "list")
    assert result.exit_code == 4 and "SURFSKY_API_TOKEN" in result.stderr


def test_skill_prints_and_installs(home, invoke, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    printed = invoke("skill")
    assert printed.exit_code == 0 and "surfsky session start" in printed.stdout
    assert printed.stdout.startswith("---\nname: surfsky-cli\n")
    assert "surfsky login" not in printed.stdout and "SURFSKY_API_TOKEN" in printed.stdout
    assert (
        f"surfsky-cli {__version__}" in printed.stdout
        and "{version}" not in printed.stdout
    )
    installed = invoke("skill", "--install")
    assert installed.exit_code == 0
    for root in (".claude/skills", ".agents/skills"):
        assert (tmp_path / root / "surfsky-cli/SKILL.md").read_text() == printed.stdout
        assert f"installed: {root}/surfsky-cli/SKILL.md" in installed.stdout
