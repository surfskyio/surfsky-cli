"""Requires SURFSKY_LIVE_TESTS=1 and API credentials; starts billed browsers."""

import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("SURFSKY_LIVE_TESTS"),
    reason="set SURFSKY_LIVE_TESTS=1; starts billed browsers",
)


def surfsky(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "surfsky_cli", *args],
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_session_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("SURFSKY_HOME", str(tmp_path))  # subprocesses inherit it
    try:
        started = surfsky("session", "start", "--idle-timeout", "120", "--json")
        assert started.returncode == 0, started.stderr
        uuid = json.loads(started.stdout)["session"]
        monkeypatch.setenv("SURFSKY_SESSION", uuid)  # every command below needs it

        opened = surfsky("goto", "https://example.com", "--snapshot", "--json")
        assert opened.returncode == 0, opened.stderr
        data = json.loads(opened.stdout)
        assert data["status"] == 200 and data["navigated"] is True
        link = next(item for item in data["snapshot"]["items"] if item["role"] == "link")

        clicked = surfsky("click", f"@{link['ref']}", "--json")
        assert clicked.returncode == 0, clicked.stderr
        assert surfsky("wait", "--url", "iana").returncode == 0
        assert "iana.org" in surfsky("get", "url").stdout

        stale = surfsky("click", f"@{link['ref']}")
        assert stale.returncode == 6 and "stale_ref" in stale.stderr

        shot = surfsky("screenshot", "-o", str(tmp_path / "s.png"))
        assert shot.returncode == 0 and (tmp_path / "s.png").stat().st_size > 1000

        status = json.loads(surfsky("status", "--json").stdout)
        assert status["alive"] is True and status["session"] == uuid
    finally:
        stopped = surfsky("session", "stop", "--json")
        assert stopped.returncode == 0, stopped.stderr
    again = json.loads(surfsky("session", "stop", "--json").stdout)  # safe to repeat
    assert again["ok"] is True and again["stopped"] is True


def test_scrape_one_shot():
    result = surfsky("scrape", "https://example.com", "--only-main-content")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("# Example Domain")
