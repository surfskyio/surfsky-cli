import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from surfsky import ServerError

from conftest import RECORD
from surfsky_cli import config, session


@pytest.fixture
def start_client(home, monkeypatch):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.with_options = Mock(return_value=client)
    client.profiles.list_active.return_value = [SimpleNamespace(internal_uuid="S2")]
    monkeypatch.setattr(config.Settings, "client", lambda self: client)
    return client


def test_start_records_and_prints(start_client, invoke, monkeypatch):
    started = {}

    async def start(client, **kwargs):
        started.update(kwargs)
        record = {**RECORD, "internal_uuid": "S2", "idle_timeout": kwargs["idle_timeout"]}
        config.save_session(record)
        config.save_state("S2", {"last_used": 1.0})
        return record

    monkeypatch.setattr(session, "start", start)
    result = invoke(
        "session",
        "start",
        "--block",
        "image",
        "--idle-timeout",
        "60",
        "--dialogs",
        "accept",
        "--json",
    )
    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {
        "ok": True,
        "session": "S2",
        "idle_timeout": 60,
        "screencast": "https://api.test/screencast?ws=wss%3A%2F%2Fapi.test%2Fscreencast%2FS1%3Ftoken%3Dx",
        "devtools": "https://api.test/proxy/S1/inspector",
    }
    assert started == {
        "profile_uuid": None,
        "idle_timeout": 60,
        "dialogs": "accept",
        "block_resources": frozenset({"image"}),
    }
    assert "note:" not in result.stderr


def test_start_refuses_profile_with_fingerprint(fake, invoke):
    result = invoke("session", "start", "--profile", "P1", "--os", "win")
    assert result.exit_code == 2 and "profile create --os" in result.stderr


@pytest.mark.parametrize("other_ids", [[], ["X9"], ["X9", "Y9"]])
def test_start_counts_live_sessions_not_local_records(
    fake, start_client, invoke, monkeypatch, other_ids
):
    # S1 is saved locally but has expired; X9/Y9 were started elsewhere.
    start_client.profiles.list_active.return_value = [
        SimpleNamespace(internal_uuid=uuid) for uuid in ["S2", *other_ids]
    ]

    async def start(client, **kwargs):
        record = {**RECORD, "internal_uuid": "S2"}
        config.save_session(record)
        return record

    monkeypatch.setattr(session, "start", start)
    result = invoke("session", "start", "--proxy", "premium", "--country", "de")
    assert result.exit_code == 0, result.output
    if other_ids:
        plural = "s" if len(other_ids) > 1 else ""
        assert f"note: {len(other_ids)} other session{plural} running" in result.stderr
    else:
        assert "note:" not in result.stderr
    assert "session: S2" in result.stdout


@pytest.mark.parametrize("error", [ServerError("boom", status_code=502), TimeoutError()])
def test_start_still_prints_session_when_live_count_fails(
    start_client, invoke, monkeypatch, error
):
    start_client.profiles.list_active.side_effect = error
    monkeypatch.setattr(session, "start", AsyncMock(return_value=RECORD))
    result = invoke("session", "start", "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["session"] == "S1"
    assert "note:" not in result.stderr
    start_client.with_options.assert_called_once_with(timeout=2, max_retries=0)


def test_stop_variants(fake, invoke, monkeypatch):
    stopped = []

    async def stop(client, uuid):
        stopped.append(uuid)
        config.delete_session(uuid)
        return True

    monkeypatch.setattr(session, "stop", stop)
    config.save_session({**RECORD, "internal_uuid": "S2"})
    assert json.loads(invoke("session", "stop", "--session", "S2", "--json").stdout) == {
        "ok": True,
        "stopped": True,
        "session": "S2",
    }
    assert json.loads(invoke("session", "stop", "--json").stdout) == {
        "ok": True,
        "stopped": True,
        "session": "S1",
    }
    assert stopped == ["S2", "S1"]
    monkeypatch.delenv("SURFSKY_SESSION")
    bare = invoke("session", "stop")
    assert bare.exit_code == 2 and "--session <uuid>" in bare.stderr
    config.save_session(dict(RECORD))
    assert json.loads(invoke("session", "stop", "--all", "--json").stdout)["stopped"] == [
        "S1"
    ]


def test_stop_failure_reports_the_cause(fake, invoke, monkeypatch):
    async def stop(client, uuid):
        raise ServerError("boom", status_code=502)

    monkeypatch.setattr(session, "stop", stop)
    data = json.loads(invoke("session", "stop", "--json").stdout)
    assert data["error"]["code"] == "api" and "boom" in data["error"]["message"]
    assert "keep billing" in data["error"]["hint"]
    assert config.load_session("S1") is not None
    failed = json.loads(invoke("session", "stop", "--all", "--json").stdout)["failed"]
    assert failed[0]["session"] == "S1" and "boom" in failed[0]["error"]


def test_stop_account_wide_asks(fake, invoke, monkeypatch):
    calls = []

    class Client:
        profiles = SimpleNamespace(stop_all=lambda: _stop_all())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

    async def _stop_all():
        calls.append("stop_all")
        return SimpleNamespace(
            stopped=["S1"], failed=[{"internal_uuid": "X9", "error": "busy"}]
        )

    config.save_session({**RECORD, "internal_uuid": "X9", "name": "other"})
    monkeypatch.setattr(config.Settings, "client", lambda self: Client())
    aborted = invoke("session", "stop", "--all", "--account")
    assert aborted.exit_code == 1 and calls == [] and "Aborted" in aborted.stderr
    data = json.loads(
        invoke("session", "stop", "--all", "--account", "--yes", "--json").stdout
    )
    assert data["stopped"] == ["S1"] and calls == ["stop_all"]
    assert config.load_session("S1") is None
    assert config.load_session("X9") is not None


def test_list_prunes_stale_records_and_devtools(fake, invoke, monkeypatch):
    class Client:
        profiles = SimpleNamespace(list_active=lambda: _active())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

    async def _active():
        return [
            SimpleNamespace(
                internal_uuid="S1",
                profile_uuid="S1",
                one_time=True,
                started_at="t1",
                active_seconds=5,
            ),
            SimpleNamespace(
                internal_uuid="X9",
                profile_uuid="P9",
                one_time=False,
                started_at="t9",
                active_seconds=9,
            ),
        ]

    monkeypatch.setattr(config.Settings, "client", lambda self: Client())
    config.save_session({**RECORD, "internal_uuid": "S2"})  # ended without us hearing
    rows = json.loads(invoke("session", "list", "--json").stdout)["items"]
    assert rows == [
        {"session": "S1", "started_at": "t1", "active_seconds": 5},
        {
            "session": "X9",
            "profile": "P9",
            "started_at": "t9",
            "active_seconds": 9,
        },
    ]
    assert config.load_session("S2") is None and config.load_session("S1") is not None
    assert json.loads(invoke("session", "devtools", "--json").stdout) == {
        "ok": True,
        "screencast": "https://api.test/screencast?ws=wss%3A%2F%2Fapi.test%2Fscreencast%2FS1%3Ftoken%3Dx",
        "devtools": "https://api.test/proxy/S1/inspector",
    }
    assert invoke("session", "devtools").stdout.startswith("screencast: https://")
