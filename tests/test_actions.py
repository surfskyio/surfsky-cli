import json

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
