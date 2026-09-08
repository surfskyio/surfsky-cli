import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from surfsky import AsyncSurfsky

TOKEN_ENV = "SURFSKY_API_TOKEN"
URL_ENV = "SURFSKY_API_BASE_URL"
SESSION_ENV = "SURFSKY_SESSION"
SESSIONS = "sessions"
STATE_SUFFIX = ".state.json"


def home() -> Path:
    return Path(os.environ.get("SURFSKY_HOME") or Path.home() / ".surfsky")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically replace the record with 0600 permissions on POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def session_path(uuid: str) -> Path:
    return home() / SESSIONS / f"{uuid}.json"


def state_path(uuid: str) -> Path:
    return home() / SESSIONS / f"{uuid}{STATE_SUFFIX}"


def load_session(uuid: str) -> dict[str, Any] | None:
    return read_json(session_path(uuid)) or None


def save_session(record: dict[str, Any]) -> None:
    write_json(session_path(record["internal_uuid"]), record)


def load_state(uuid: str) -> dict[str, Any]:
    return read_json(state_path(uuid))


def save_state(uuid: str, state: dict[str, Any]) -> None:
    write_json(state_path(uuid), state)


def delete_session(uuid: str) -> None:
    session_path(uuid).unlink(missing_ok=True)
    state_path(uuid).unlink(missing_ok=True)


def list_sessions() -> list[dict[str, Any]]:
    folder = home() / SESSIONS
    if not folder.is_dir():
        return []
    paths = sorted(p for p in folder.glob("*.json") if not p.name.endswith(STATE_SUFFIX))
    return [record for record in (read_json(p) for p in paths) if record]


def resolve(ref: str) -> str | None:
    """Resolve a local session ID prefix; reject ambiguous matches."""
    prefixed = [
        s["internal_uuid"] for s in list_sessions() if s["internal_uuid"].startswith(ref)
    ]
    if len(prefixed) > 1:
        raise ValueError(
            f"{ref!r} matches {len(prefixed)} session ids; give more characters"
        )
    return prefixed[0] if prefixed else None


@dataclass
class Settings:
    """Command-line values override environment variables."""

    api_token: str | None = None
    base_url: str | None = None
    session: str | None = None

    def token(self) -> tuple[str | None, str]:
        if self.api_token:
            return self.api_token, "flag"
        if value := os.environ.get(TOKEN_ENV):
            return value, "env"
        return None, "none"

    def url(self) -> str | None:
        return self.base_url or os.environ.get(URL_ENV)

    def session_ref(self) -> str | None:
        return self.session or os.environ.get(SESSION_ENV)

    def session_id(self) -> str | None:
        ref = self.session_ref()
        if not ref:
            return None
        return resolve(ref) or ref

    def client(self) -> AsyncSurfsky:
        # the SDK raises ConfigurationError for a missing token or URL (exit 4 upstream)
        return AsyncSurfsky(api_token=self.token()[0], base_url=self.url())
