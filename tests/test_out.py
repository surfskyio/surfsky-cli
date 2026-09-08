import errno
import json

import click
import pytest
from click.testing import CliRunner
from surfsky import (
    AuthenticationError,
    BrowserTimeoutError,
    CDPError,
    ConfigurationError,
    MonthlySessionLimitError,
    RateLimitError,
    ServerError,
)
from surfsky.types import ProfileRef

from surfsky_cli import out
from surfsky_cli.main import cli, hoist, suggest


@pytest.fixture(autouse=True)
def text_mode(monkeypatch):
    monkeypatch.delenv("SURFSKY_JSON", raising=False)


def test_plain_scalar_render():
    assert out.plain([ProfileRef(uuid="u")]) == [{"uuid": "u"}]
    assert (
        out.scalar(None) == "null"
        and out.scalar(True) == "true"
        and out.scalar("s") == "s"
    )
    assert out.render({"a": 1, "b": "x"}) == "a: 1\nb: x"
    assert out.render([{"a": 1, "b": "x"}, {"a": 2}]) == "a: 1\nb: x\n\na: 2"
    assert out.render(["x", "y"]) == "x\ny"


def test_envelope_shapes():
    assert out.envelope({"a": 1}) == {"ok": True, "a": 1}
    assert out.envelope([{"a": 1}]) == {"ok": True, "items": [{"a": 1}], "count": 1}
    assert out.envelope("v") == {"ok": True, "value": "v"}
    assert out.envelope(ProfileRef(uuid="u")) == {"ok": True, "uuid": "u"}


def test_emit_text_json_and_file(tmp_path):
    @click.command()
    @out.output_options
    def cmd(**kw):
        out.emit({"a": 1}, text="raw", **kw)

    runner = CliRunner()
    assert runner.invoke(cmd, []).stdout == "raw\n"
    assert runner.invoke(cmd, ["--json"]).stdout == '{"ok": true, "a": 1}\n'
    assert (
        runner.invoke(cmd, ["--json", "--pretty"]).stdout
        == '{\n  "ok": true,\n  "a": 1\n}\n'
    )
    target = tmp_path / "o.json"
    result = runner.invoke(cmd, ["--json", "-o", str(target)])
    assert json.loads(target.read_text()) == {"ok": True, "a": 1}
    assert result.stderr == f"saved: {target}\n"


def test_json_env_default(monkeypatch):
    monkeypatch.setenv("SURFSKY_JSON", "1")

    @click.command()
    @out.output_options
    def cmd(**kw):
        out.emit({"a": 1}, **kw)

    assert CliRunner().invoke(cmd, []).stdout == '{"ok": true, "a": 1}\n'


@pytest.mark.parametrize(
    ("exc", "code", "exit_code", "hint"),
    [
        (out.NoSession("no browser session"), "no_session", 3, "session start"),
        (out.SessionGone("session x is gone"), "session_gone", 3, "session start"),
        (
            AuthenticationError("bad token", status_code=401),
            "auth",
            4,
            "SURFSKY_API_TOKEN",
        ),
        (ConfigurationError("pass api_token"), "auth", 4, "SURFSKY_API_TOKEN"),
        (BrowserTimeoutError("'#x' was not visible within 10s"), "timeout", 5, None),
        (out.StaleRef("refs are from a, page is b"), "stale_ref", 6, "surfsky snapshot"),
        (
            out.NotFound("nothing matches '#x'", hint="2 iframes"),
            "not_found",
            6,
            "2 iframes",
        ),
        (MonthlySessionLimitError("cap", status_code=429), "quota", 7, None),
        (
            RateLimitError(
                "full", status_code=429, body={"code": "parallel_browsers_limit_reached"}
            ),
            "plan_full",
            7,
            "session list",
        ),
        (RateLimitError("slow", status_code=429), "rate_limit", 7, None),
        (ServerError("boom", status_code=502), "api", 1, None),
        (CDPError("Human.click 'x': timeout waiting"), "timeout", 5, None),
        (CDPError("Human.click 'x': bad"), "browser", 1, None),
        (ValueError("unknown resource types"), "error", 1, None),
        (KeyError("ws_url"), "error", 1, None),
    ],
)
def test_classify_and_show(exc, code, exit_code, hint, monkeypatch):
    @click.command()
    def boom():
        raise exc

    monkeypatch.setitem(cli.commands, "boom", boom)
    result = CliRunner().invoke(cli, ["boom"])
    assert result.exit_code == exit_code
    assert result.stderr.startswith(f"error [{code}]: {exc}")
    assert (hint in result.stderr) if hint else ("hint:" not in result.stderr)
    assert result.stdout == ""

    monkeypatch.setenv("SURFSKY_JSON", "1")
    result = CliRunner().invoke(cli, ["boom"])
    body = json.loads(result.stdout)
    assert body["ok"] is False and body["error"]["code"] == code
    assert body["error"]["retryable"] == (
        code in {"timeout", "rate_limit", "plan_full", "network"}
    )
    assert result.stderr == ""


def test_click_exit_passes_through(monkeypatch):
    @click.command()
    def quit_():
        click.echo("bye")
        raise click.exceptions.Exit(1)

    monkeypatch.setitem(cli.commands, "quit", quit_)
    result = CliRunner().invoke(cli, ["quit"])
    assert result.exit_code == 1 and result.stdout == "bye\n" and result.stderr == ""


def test_global_options_anywhere(monkeypatch):
    seen = {}

    @click.command()
    @click.argument("word")
    @out.pass_settings
    def probe(settings, word):
        seen.update(vars(settings), word=word)

    monkeypatch.setitem(cli.commands, "probe", probe)
    args = hoist(["probe", "hello", "--session", "work", "--api-token=t", "-v"])
    assert args == ["--session", "work", "--api-token=t", "-v", "probe", "hello"]
    assert hoist(["probe", "--", "--session"]) == ["probe", "--", "--session"]
    raw = ["probe", "hello", "--session", "work", "--api-token=t", "-v"]
    result = CliRunner().invoke(cli, raw)  # Cli.parse_args hoists on its own
    assert result.exit_code == 0, result.stderr
    assert seen == {
        "api_token": "t",
        "base_url": None,
        "session": "work",
        "word": "hello",
    }


def test_suggestions():
    assert suggest("start", ["session start", "session stop", "goto"]) == "session start"
    assert suggest("zzz", ["goto"]) is None
    result = CliRunner().invoke(cli, ["start"])
    assert result.exit_code == 2 and "did you mean 'session start'" in result.stderr
    assert result.stderr.startswith("error [usage]:")


def test_bare_group_names_its_subcommands():
    result = CliRunner().invoke(cli, ["get"])
    assert result.exit_code == 2
    assert "needs a subcommand: url, title, text" in result.stderr
    assert "hint: cli get --help" in result.stderr


def test_broken_pipe_is_left_to_click(monkeypatch):
    @click.command()
    def probe():
        raise BrokenPipeError(errno.EPIPE, "Broken pipe")

    monkeypatch.setitem(cli.commands, "probe", probe)
    result = CliRunner().invoke(cli, ["probe"])
    assert result.exit_code == 1 and "error [" not in result.stderr


def test_plain_reaches_models_inside_dicts_and_tuples():
    from pydantic import BaseModel

    class Item(BaseModel):
        uuid: str

    assert out.plain({"a": Item(uuid="u"), "b": (Item(uuid="v"),)}) == {
        "a": {"uuid": "u"},
        "b": [{"uuid": "v"}],
    }


def test_usage_error_json():
    result = CliRunner().invoke(cli, ["click", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "usage"
    assert result.stderr == ""


def test_json_mode_does_not_leak_between_invocations(monkeypatch):
    runner = CliRunner()
    result = runner.invoke(cli, ["click", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "usage"

    # Command resolution fails before any output option callback can run.
    result = runner.invoke(cli, ["start"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr.startswith("error [usage]:")

    monkeypatch.setenv("SURFSKY_JSON", "1")
    result = runner.invoke(cli, ["start"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "usage"
    assert result.stderr == ""

    monkeypatch.delenv("SURFSKY_JSON")
    result = runner.invoke(cli, ["start"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr.startswith("error [usage]:")


def test_error_keeps_output_mode_after_context_closes(capsys):
    with click.Context(cli) as ctx:
        out.set_json(ctx, click.Option(["--json"]), True)
        error = out.CliError("failed")

    with click.Context(cli):
        text_error = out.CliError("text failure")
        error.show()
        text_error.show()

    captured = capsys.readouterr()
    assert json.loads(captured.out)["error"]["message"] == "failed"
    assert captured.err == "error [error]: text failure\n"


def test_help_is_sectioned():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    text = result.stdout
    assert "Setup and one-shot:" in text
    assert (
        text.index("Setup and one-shot:")
        < text.index("Session:")
        < text.index("Navigate:")
    )
    assert "surfsky session start" in text  # the quick start epilog
