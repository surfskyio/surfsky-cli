import os

import pytest

from surfsky_cli import config


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SURFSKY_HOME", str(tmp_path))
    for name in ("SURFSKY_API_TOKEN", "SURFSKY_API_BASE_URL", "SURFSKY_SESSION"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def record(uuid, name=None):
    return {
        "internal_uuid": uuid,
        "ws_url": f"wss://x/{uuid}",
        "name": name,
    }


def test_session_and_state_files_round_trip(isolated_home):
    config.save_session(record("abc-1", "work"))
    assert config.load_session("abc-1")["name"] == "work"
    assert config.load_state("abc-1") == {}
    config.save_state("abc-1", {"last_used": 1.0, "refs": {"1": "a"}})
    assert config.load_state("abc-1")["refs"] == {"1": "a"}
    assert [s["internal_uuid"] for s in config.list_sessions()] == ["abc-1"]
    assert not any(
        p.name.endswith(".tmp") for p in (isolated_home / "sessions").iterdir()
    )
    config.delete_session("abc-1")
    assert config.load_session("abc-1") is None
    assert config.load_state("abc-1") == {}
    assert config.list_sessions() == []


def test_session_files_are_private_and_atomic(isolated_home, monkeypatch):
    config.save_session(record("abc-1"))
    path = isolated_home / "sessions" / "abc-1.json"
    if os.name == "posix":
        assert (path.stat().st_mode & 0o777) == 0o600
    calls = []
    real_replace = os.replace

    def spy(src, dst):
        calls.append((str(src), str(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    config.save_state("abc-1", {"last_used": 1.0})
    target = str(isolated_home / "sessions" / "abc-1.state.json")
    assert calls and calls[-1][1] == target and calls[-1][0] != target


def test_resolve_by_uuid_prefix():
    config.save_session(record("aaaa-1"))
    config.save_session(record("aaab-2"))
    assert config.resolve("aaaa-1") == "aaaa-1"
    assert config.resolve("aaab") == "aaab-2"
    assert config.resolve("nope") is None
    with pytest.raises(ValueError, match="more characters"):
        config.resolve("aaa")


def test_settings_precedence(monkeypatch):
    assert config.Settings().token() == (None, "none")
    assert config.Settings().url() is None
    monkeypatch.setenv("SURFSKY_API_TOKEN", "from-env")
    monkeypatch.setenv("SURFSKY_API_BASE_URL", "https://env")
    assert config.Settings().token() == ("from-env", "env")
    assert config.Settings().url() == "https://env"
    assert config.Settings(api_token="from-flag").token() == ("from-flag", "flag")
    assert config.Settings(base_url="https://flag").url() == "https://flag"


def test_session_id_is_explicit_only(monkeypatch):
    assert config.Settings().session_id() is None
    config.save_session(record("abcd-1"))
    assert config.Settings().session_id() is None  # no hidden default
    monkeypatch.setenv("SURFSKY_SESSION", "abcd")
    assert config.Settings().session_id() == "abcd-1"
    assert config.Settings(session="abcd-1").session_id() == "abcd-1"
    assert (
        config.Settings(session="ghost").session_id() == "ghost"
    )  # unknown: reported later


def test_client_uses_resolved_values(monkeypatch):
    monkeypatch.setenv("SURFSKY_API_TOKEN", "tok")
    monkeypatch.setenv("SURFSKY_API_BASE_URL", "https://env/")
    assert config.Settings().client().base_url == "https://env"
