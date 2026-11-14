import json

import pytest
from surfsky import BrowserTimeoutError, CDPError
from surfsky.types import ChallengeResult

HEAD = "url: https://e.test/a\ntitle: E\nnavigated: true\n"
PAGE = {"ok": True, "url": "https://e.test/a", "title": "E", "navigated": True}
BLOCKED = "the site refused this browser: start a new session with another --os or proxy"
LOADING = "the page may be partly loaded"
FAILED = "challenge check failed: the page may be a challenge page, check 'get title'"


@pytest.mark.parametrize(
    ("answer", "status", "text", "fields"),
    [
        (ChallengeResult(status="none"), 200, "status: 200\n", {}),
        (
            ChallengeResult(status="solved", antibot="cloudflare", cost_usd=0.0012),
            200,
            "status: 200\nchallenge: solved\nbilled_usd: 0.0012\n",
            {"challenge": "solved", "billed_usd": 0.0012},
        ),
        (
            ChallengeResult(status="passed", antibot="datadome"),
            200,
            "status: 200\nchallenge: passed\n",
            {"challenge": "passed"},
        ),
        (
            ChallengeResult(status="not_solved", reason="solve_failed"),
            403,
            "status: 403\nchallenge: not solved\nreason: solve_failed\n",
            {"challenge": "not solved", "reason": "solve_failed"},
        ),
        (
            ChallengeResult(status="blocked", antibot="akamai"),
            403,
            f"status: 403\nchallenge: blocked\nnote: {BLOCKED}\n",
            {"challenge": "blocked", "note": BLOCKED},
        ),
    ],
    ids=lambda value: getattr(value, "status", None),
)
def test_goto_reports_the_challenge_outcome(fake, invoke, answer, status, text, fields):
    fake.page.challenge_result, fake.page.status = answer, status
    result = invoke("goto", "e.test/a")
    assert result.exit_code == 0, result.stderr
    assert result.stdout == HEAD + text
    fake.page._url, fake.page.status = "https://e.test/", status
    data = json.loads(invoke("goto", "e.test/a", "--json").stdout)
    assert data == {**PAGE, "status": status, **fields}


def test_the_pass_sends_no_timeout(fake, invoke):
    assert invoke("goto", "e.test/a").exit_code == 0
    assert fake.page.called("pass_challenge") == [("pass_challenge", (), {"solve": True})]


def test_a_solve_that_was_charged_and_failed_shows_its_cost(fake, invoke):
    fake.page.challenge_result = ChallengeResult(status="not_solved", cost_usd=0.0024)
    data = json.loads(invoke("goto", "e.test/a", "--json").stdout)
    assert data["challenge"] == "not solved" and data["billed_usd"] == 0.0024


def test_a_charge_on_a_blocked_page_is_shown(fake, invoke):
    fake.page.challenge_result = ChallengeResult(status="blocked", cost_usd=0.0024)
    text = invoke("goto", "e.test/a").stdout
    assert f"challenge: blocked\nbilled_usd: 0.0024\nnote: {BLOCKED}\n" in text


@pytest.mark.parametrize(
    ("answer", "fields"),
    [
        (ChallengeResult(status="passed"), {"challenge": "passed"}),
        (
            ChallengeResult(status="not_solved", reason="timeout"),
            {"challenge": "not solved", "reason": "timeout"},
        ),
    ],
)
def test_no_solve_uses_the_ordinary_outcomes(fake, invoke, answer, fields):
    fake.page.challenge_result = answer
    data = json.loads(invoke("goto", "e.test/a", "--no-solve", "--json").stdout)
    assert data == {**PAGE, "status": 200, **fields}
    assert fake.page.called("pass_challenge") == [
        ("pass_challenge", (), {"solve": False})
    ]


def test_no_solve_on_an_ordinary_page_has_no_challenge_field(fake, invoke):
    data = json.loads(invoke("goto", "e.test/a", "--no-solve", "--json").stdout)
    assert "challenge" not in data


@pytest.mark.parametrize("command", ["back", "reload"])
def test_history_and_reload_pass_a_challenge(fake, invoke, command):
    fake.page.challenge_result = ChallengeResult(status="passed")
    assert json.loads(invoke(command, "--json").stdout)["challenge"] == "passed"


def test_a_page_still_loading_after_the_challenge_is_a_note(fake, invoke):
    fake.page.challenge_result = ChallengeResult(
        status="solved", reason="load_timeout", cost_usd=0.0012
    )
    data = json.loads(invoke("goto", "e.test/a", "--json").stdout)
    assert data["challenge"] == "solved" and data["note"] == LOADING


def test_a_partly_loaded_page_is_noted_once(fake, invoke):
    async def goto(url, **kwargs):
        fake.page._url = url
        raise BrowserTimeoutError("timed out")

    fake.page.goto = goto
    fake.page.challenge_result = ChallengeResult(status="passed", reason="load_timeout")
    note = json.loads(invoke("goto", "e.test/slow", "--json").stdout)["note"]
    assert note == f"navigation did not reach 'load'; {LOADING}"


@pytest.mark.parametrize(
    "error",
    [CDPError("Failed to pass the challenge"), BrowserTimeoutError("no reply in 53s")],
)
def test_a_failed_challenge_check_still_reports_the_page(fake, invoke, error):
    fake.page.challenge_result = error
    result = invoke("goto", "e.test/a", "--json")
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {**PAGE, "status": 200, "note": FAILED}


def test_a_load_that_never_completes_is_a_note_not_an_error(fake, invoke):
    async def goto(url, **kwargs):
        fake.page._url = url
        raise BrowserTimeoutError("timed out")

    fake.page.goto = goto
    data = json.loads(invoke("goto", "e.test/slow", "--json").stdout)
    assert data["url"] == "https://e.test/slow" and "did not reach 'load'" in data["note"]


def test_a_navigation_that_never_left_the_page_is_a_timeout(fake, invoke):
    async def goto(url, **kwargs):
        raise BrowserTimeoutError("timed out")

    fake.page.goto = goto
    result = invoke("goto", "e.test/slow")
    assert result.exit_code == 5 and "error [timeout]" in result.stderr
    assert not fake.page.called("pass_challenge")


def test_help_says_what_no_solve_does(invoke):
    for command in ("goto", "back", "forward", "reload"):
        text = " ".join(invoke(command, "--help").stdout.split())
        assert "--no-solve" in text and "cost money on pay-as-you-go" in text
        assert "nothing is billed" in text and "pass by itself" in text
