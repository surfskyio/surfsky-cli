import json

import pytest
from surfsky import CDPError

from surfsky_cli import config

FOUND = {
    "items": [{"ref": 3, "role": "link", "name": "Sign in", "selector": "a.si"}],
    "total": 1,
    "unreachable": [],
}


def test_click_by_ref_selector_and_text(fake, invoke):
    result = invoke("click", "@1")
    assert result.exit_code == 0, result.stderr
    assert result.stdout == "url: https://e.test/\ntitle: E\nnavigated: false\n"
    assert fake.page.called("click")[0] == (
        "click",
        ("a.first",),
        {"button": None, "modifiers": None, "timeout": 10.0},
    )
    fake.page.after_click_url = "https://e.test/next"
    data = json.loads(
        invoke(
            "click",
            "#go",
            "--double",
            "--modifiers",
            "Shift,Control",
            "--button",
            "right",
            "--json",
        ).stdout
    )
    assert data["navigated"] is False  # dblclick is a Recorder call: no url change
    assert fake.page.called("dblclick")[0][2] == {
        "button": "right",
        "modifiers": ["Shift", "Control"],
        "timeout": 10.0,
    }
    assert json.loads(invoke("click", "#go", "--json").stdout)["navigated"] is True
    fake.page.evaluate_result = FOUND
    fake.page._url = "https://e.test/"
    invoke("click", "text=sign in")
    assert fake.page.called("click")[-1][1] == ("a.si",)


def test_click_snapshot_follows_late_navigation(fake, invoke):
    async def evaluate(expression, *args, **kwargs):
        if fake.page._url == "https://e.test/":
            fake.page._url = "https://e.test/next"
            return {"items": [], "total": 0, "unreachable": []}
        return FOUND

    fake.page.evaluate = evaluate
    result = invoke("click", "#go", "-s")
    assert result.stdout == (
        'url: https://e.test/next\ntitle: E\nnavigated: true\n[@3] link "Sign in"\n'
    )
    assert config.load_state("S1")["refs"] == {"3": "a.si"}


def test_click_snapshot_says_when_the_page_never_stopped_navigating(fake, invoke):
    hops = iter(range(10))

    async def evaluate(expression, *args, **kwargs):
        fake.page._url = f"https://e.test/{next(hops)}"
        return {"items": [], "total": 0, "unreachable": []}

    fake.page.evaluate = evaluate
    result = invoke("click", "#go", "-s")
    assert result.stdout == (
        "url: https://e.test/2\ntitle: E\nnavigated: true\n"
        "note: the page was still navigating; the snapshot may be incomplete\n"
    )


def test_click_errors(fake, invoke):
    stale = invoke("click", "@9")
    assert stale.exit_code == 6 and stale.stderr.startswith(
        "error [stale_ref]: unknown ref @9"
    )
    assert "surfsky snapshot" in stale.stderr
    fake.page.counts["a.first"] = 0
    assert "no longer on the page" in invoke("click", "@1").stderr
    xpath = invoke("click", "//a")
    assert xpath.exit_code == 1 and "XPath" in xpath.stderr
    fake.page.evaluate_result = {
        "items": [],
        "total": 0,
        "unreachable": [{"kind": "iframe"}],
    }
    missing = invoke("click", "text=nope")
    assert missing.exit_code == 6 and "hint: the page has 1 iframe" in missing.stderr


def test_fill_type_press_select_hover(fake, invoke):
    assert invoke("fill", "@1", "hello").exit_code == 0
    assert fake.page.called("fill")[0][1] == ("a.first", "hello")
    invoke("type", "#q", "more")
    assert fake.page.called("type")[0][1] == ("#q", "more")
    invoke("type", "@focused", "typed")
    assert fake.page.keyboard.called("type")[0][1] == ("typed",)
    invoke("press", "Enter", "--modifiers", "Shift")
    assert fake.page.keyboard.called("press")[0] == (
        "press",
        ("Enter",),
        {"modifiers": ["Shift"]},
    )
    data = json.loads(invoke("select", "#s", "Two", "--label", "--json").stdout)
    assert data["selected"] == "Two" and data["navigated"] is False
    assert fake.page.called("select_option")[0] == (
        "select_option",
        ("#s", None),
        {"label": "Two"},
    )
    invoke("hover", "#h")
    assert fake.page.called("hover")[0] == ("hover", ("#h",), {"timeout": 10.0})


def test_scroll_and_mouse(fake, invoke):
    invoke("scroll")  # the fake viewport is 1000px tall
    default = fake.page.called("scroll")[0][2]
    assert default["delta_x"] is None and 600 <= default["delta_y"] <= 900
    invoke("scroll", "--y=-200")
    assert fake.page.called("scroll")[1][2] == {"delta_x": None, "delta_y": -200.0}
    invoke("scroll", "--to", "@1")
    assert fake.page.called("scroll_into_view")[0][1] == ("a.first",)
    invoke("scroll", "--top")
    assert fake.page.called("scroll_to")[0][2] == {"y": 0}
    fake.page.evaluate_result = 4200
    invoke("scroll", "--bottom")
    assert fake.page.called("scroll_to")[1][2] == {"y": 4200}
    invoke("mouse", "click", "10", "20", "--button", "right")
    assert fake.page.mouse.called("click")[0] == (
        "click",
        (10.0, 20.0),
        {"button": "right"},
    )
    invoke("mouse", "move", "1", "2")
    assert fake.page.mouse.called("move")[0][1] == (1.0, 2.0)
    invoke("mouse", "drag", "1", "2", "3", "4")
    assert fake.page.mouse.called("drag")[0][2] == {
        "start_x": 1.0,
        "start_y": 2.0,
        "end_x": 3.0,
        "end_y": 4.0,
    }


def test_wait(fake, invoke):
    assert invoke("wait").exit_code == 2
    assert (
        invoke(
            "wait", "--sleep", "0.01", "--url", "/done", "--load", "domcontentloaded"
        ).exit_code
        == 0
    )
    assert fake.page.called("wait_for_url")[0] == (
        "wait_for_url",
        ("/done",),
        {"timeout": 30.0},
    )
    assert fake.page.called("wait_for_load_state")[0][1] == ("domcontentloaded",)
    invoke("wait", "@1", "--timeout", "5")
    assert fake.page.called("wait_for_selector")[0] == (
        "wait_for_selector",
        ("a.first",),
        {"timeout": 5.0},
    )
    invoke("wait", "#spinner", "--gone")
    assert fake.page.called("wait_for_function")[0][1][1] == "#spinner"
    assert invoke("wait", "--load", "networkidle").exit_code == 2


def test_get(fake, invoke):
    assert invoke("get", "url").stdout == "https://e.test/\n"
    assert invoke("get", "title").stdout == "E\n"
    assert invoke("get", "text").stdout == "text of body\n"
    assert invoke("get", "text", "@1").stdout == "text of a.first\n"
    assert invoke("get", "html", "#x").stdout == "<div>#x</div>\n"
    assert "<h1>Hi</h1>" in invoke("get", "html").stdout
    assert invoke("get", "attr", "#x", "href").stdout == "href-of-#x\n"
    assert invoke("get", "attr", "#x", "missing").stdout == "\n"
    assert invoke("get", "count", "li").stdout == "1\n"
    fake.page.evaluate_result = "typed value"
    assert invoke("get", "value", "#q").stdout == "typed value\n"
    assert json.loads(invoke("get", "url", "--json").stdout) == {
        "ok": True,
        "value": "https://e.test/",
    }
    fake.page.counts["#gone"] = 0
    missing = invoke("get", "text", "#gone")
    assert missing.exit_code == 6 and missing.stderr.startswith(
        "error [not_found]: nothing matches '#gone'"
    )


def test_is_always_exits_zero(fake, invoke):
    shown = invoke("is", "visible", "#x")
    assert shown.exit_code == 0 and shown.stdout == "true\n"
    hidden = invoke("is", "visible", "#hidden")
    assert hidden.exit_code == 0 and hidden.stdout == "false\n"
    fake.page.counts["#gone"] = 0
    assert invoke("is", "present", "#gone").stdout == "false\n"
    assert json.loads(invoke("is", "present", "li", "--json").stdout) == {
        "ok": True,
        "present": True,
    }


def test_screenshot(fake, invoke, tmp_path):
    target = tmp_path / "s.png"
    result = invoke("screenshot", "-o", str(target), "--full-page", "--selector", "@1")
    assert result.exit_code == 0, result.stderr
    assert result.stdout == f"{target}\n" and target.read_bytes() == b"\x89PNG-fake"
    assert fake.page.called("bring_to_front")
    assert fake.page.called("screenshot")[0][2] == {
        "selector": "a.first",
        "full_page": True,
    }


def test_cookies(fake, invoke, tmp_path):
    assert invoke("cookies", "get").stdout == "[]\n"
    jar = tmp_path / "c.json"
    jar.write_text('[{"name": "a", "value": "1", "domain": "e.test"}]')
    assert json.loads(invoke("cookies", "set", f"@{jar}", "--json").stdout) == {
        "ok": True,
        "set": 1,
    }
    assert fake.page.called("set_cookies")[0][1][0][0]["name"] == "a"
    assert invoke("cookies", "clear").exit_code == 0 and fake.page.called("clear_cookies")


def test_cookies_set_bad_json(fake, invoke):
    result = invoke("cookies", "set", "nope")
    assert result.exit_code == 1
    assert result.stderr.startswith("error [error]: cookies is not valid JSON")


def test_screenshot_json_error_is_json(home, invoke):
    result = invoke("screenshot", "--json")
    assert result.exit_code == 3
    assert json.loads(result.stdout)["error"]["code"] == "no_session"


def test_eval_and_cdp(fake, invoke):
    fake.page.evaluate_result = {"n": 1}
    assert invoke("eval", "(a, b) => a + b", "1", "x").stdout == '{"n": 1}\n'
    assert fake.page.called("evaluate")[0] == (
        "evaluate",
        ("(a, b) => a + b", 1, "x"),
        {"isolated": True},
    )
    invoke("eval", "document.title", "--main-world")
    assert fake.page.called("evaluate")[1][2] == {"isolated": False}
    assert json.loads(invoke("cdp", "Page.getFrameTree", "--json").stdout) == {
        "ok": True,
        "method": "Page.getFrameTree",
    }
    invoke("cdp", "Target.getTargets", "--browser")
    assert fake.browser.cdp.called("send")[0][1] == ("Target.getTargets", None)
    warned = invoke("cdp", "Runtime.enable")
    assert "warning: Runtime.enable is observable" in warned.stderr
    assert config.load_state("S1")["refs"] == {
        "1": "a.first"
    }  # nothing above touched refs


ACTIONS = (["click", "#go"], ["press", "Enter"], ["mouse", "click", "1", "2"])


@pytest.mark.parametrize("command", ACTIONS)
def test_an_action_waits_for_a_navigation_that_commits_late(fake, invoke, command):
    fake.page.navigates = ("https://e.test/next", 0.5)  # a slow form submit
    data = json.loads(invoke(*command, "--json").stdout)
    assert data["navigated"] is True and data["url"] == "https://e.test/next"
    assert fake.page.called("wait_for_load_state")[0][1:] == (
        ("load",),
        {"timeout": 10.0},
    )


@pytest.mark.parametrize("command", ACTIONS)
def test_an_action_that_starts_no_navigation_does_not_wait_for_load(
    fake, invoke, command
):
    # a page still loading would hold wait_for_load_state for its whole timeout
    data = json.loads(invoke(*command, "--json").stdout)
    assert data["navigated"] is False
    assert not fake.page.called("wait_for_load_state")


def test_a_click_that_starts_a_download_does_not_wait_for_load(fake, invoke):
    fake.page.navigates = (None, 0.05)
    data = json.loads(invoke("click", "#file", "--json").stdout)
    assert data["navigated"] is False
    assert not fake.page.called("wait_for_load_state")


def test_fill_does_not_wait_for_load(fake, invoke):
    assert invoke("fill", "@1", "hello").exit_code == 0
    assert not fake.page.called("wait_for_load_state")


@pytest.fixture
def no_refocus_wait(monkeypatch):
    monkeypatch.setattr("surfsky_cli.text_input.REFOCUS_WAIT", 0)


def test_typing_is_retried_only_when_nothing_was_typed(fake, invoke, no_refocus_wait):
    page = fake.page
    page.focus_misses = 1  # a dialog opened under the click: no key was sent
    done = invoke("fill", "#q", "Lisbon")
    assert done.exit_code == 0 and "focus" not in done.stderr
    assert len(page.called("fill")) == 2 and page.field["value"] == "Lisbon"
    # the keys were sent and the page moved focus: reported, never typed again
    page.calls.clear()
    page.focus_steals = 1
    failed = invoke("fill", "#q", "Porto")
    assert failed.exit_code == 1 and "moved focus" in failed.stderr
    assert len(page.called("fill")) == 1
    # the error names the agent's target, not the selector the page controls
    for command in ("fill", "type"):
        page.focus_misses = 2
        failed = invoke(command, "@1", "Porto")
        assert failed.exit_code == 1 and "@1 did not take focus" in failed.stderr
        assert "a.first" not in failed.stderr
    assert len(page.called("type")) == 2


def test_typing_never_sends_the_text_twice(fake, invoke, no_refocus_wait):
    page = fake.page

    def act(command, text="Lisbon"):
        page.calls.clear()
        done = invoke(command, "#q", text)
        assert done.exit_code == 0, done.stderr
        assert len(page.called(command)) == 1
        assert text not in done.stdout  # the field's value stays out of the output

    # a grid cell, a canvas, a div with tabindex: focusable, with no value to read
    page.field = {"editable": False, "value": None, "focused": True}
    act("type")
    # a chat box or a tag input that clears itself
    page.field = {"editable": True, "value": "", "focused": True}
    page.typed = lambda text, replace=False: None
    act("type")
    act("fill")
    # a masked field shows the text in another form
    page.typed = lambda text, replace=False: page.field.update(value="+1 (555)")
    act("fill", "1555")
    del page.typed
    # the same value again
    page.field = {"editable": True, "value": "Lisbon", "focused": True}
    act("fill")
    # typing that makes the page navigate leaves no field to read
    page.check_error = CDPError("Cannot find context with specified id")
    act("type", "123456")
    page.check_error = None
    # a field the page replaced, or one inside a shadow root
    page.field = None
    act("type")


def test_fill_with_empty_text_clears_the_field(fake, invoke):
    fake.page.field["value"] = "old"
    assert invoke("fill", "#q", "").exit_code == 0
    assert fake.page.called("fill")[0][1] == ("#q", "") and fake.page.field["value"] == ""


def test_type_into_the_focused_element_needs_one_that_takes_text(fake, invoke):
    page = fake.page
    page.focus_steals = 1
    assert "moved focus" in invoke("type", "@focused", "Lisbon").stderr
    page.field = {"editable": False, "value": None, "focused": True}  # a button
    page.keyboard.calls.clear()
    failed = invoke("type", "@focused", "Lisbon")
    assert failed.exit_code == 1 and "no editable element has focus" in failed.stderr
    assert not page.keyboard.called("type")
    # a frame takes the keys and shows no value
    page.field = {"editable": True, "value": None, "focused": True}
    assert invoke("type", "@focused", "Lisbon").exit_code == 0


@pytest.mark.parametrize(
    "command",
    [("fill", "#q", "Lisbon"), ("type", "#q", "Lisbon"), ("hover", "#q"), ("scroll",)],
)
def test_every_action_can_attach_a_limited_snapshot(fake, invoke, command):
    fake.page.evaluate_result = FOUND
    result = invoke(*command, "-s", "-i", "--limit", "5")
    assert result.exit_code == 0, result.stderr
    assert result.stdout.splitlines()[-1] == '[@3] link "Sign in"'
    walk = [
        call for call in fake.page.called("evaluate") if call[1][1:] == (5, True, None)
    ]
    assert len(walk) == 1
    assert config.load_state("S1")["refs"] == {"3": "a.si"}
    data = json.loads(invoke(*command, "-s", "--json").stdout)
    assert data["snapshot"]["items"][0]["ref"] == 3


def test_goto_snapshot_takes_the_snapshot_options(fake, invoke):
    fake.page.evaluate_result = FOUND
    assert invoke("goto", "e.test/b", "-s", "-i", "--limit", "7").exit_code == 0
    assert fake.page.called("evaluate")[-1][1][1:] == (7, True, None)


@pytest.mark.parametrize("option", [["-i"], ["--limit", "5"]])
@pytest.mark.parametrize("command", [["click", "#go"], ["goto", "e.test"], ["scroll"]])
def test_snapshot_options_without_the_snapshot_are_a_usage_error(
    fake, invoke, command, option
):
    result = invoke(*command, *option)
    assert result.exit_code == 2 and "-s" in result.stderr
    assert not fake.page.calls
