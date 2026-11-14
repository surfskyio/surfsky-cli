import json

from surfsky_cli import config
from surfsky_cli.commands import page as page_cmd

SNAP = {
    "items": [
        {
            "ref": 1,
            "role": "link",
            "name": "x",
            "selector": "a.x",
            "href": "https://e.test/x",
        }
    ],
    "total": 1,
    "unreachable": [],
}


def test_no_session_is_exit_3(home, invoke):
    result = invoke("goto", "https://e.test/")
    assert result.exit_code == 3
    assert result.stderr.startswith("error [no_session]: no session given")
    assert "session start" in result.stderr and "--session <uuid>" in result.stderr


def test_goto_reports_status_and_navigation(fake, invoke):
    result = invoke("goto", "e.test/a")
    assert result.exit_code == 0, result.stderr
    assert (
        result.stdout == "url: https://e.test/a\ntitle: E\nnavigated: true\nstatus: 200\n"
    )
    assert fake.page.called("goto")[0] == (
        "goto",
        ("https://e.test/a",),
        {"wait_until": "load", "timeout": 30.0},
    )
    assert (
        json.loads(invoke("goto", "https://e.test/a", "--json").stdout)["navigated"]
        is False
    )


def test_goto_with_snapshot_saves_refs(fake, invoke):
    fake.page.evaluate_result = SNAP
    result = invoke("goto", "https://e.test/b", "-s")
    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert (
        lines[0] == "url: https://e.test/b"
        and lines[-1] == '[@1] link "x" href=https://e.test/x'
    )
    state = config.load_state("S1")
    assert state["refs"] == {"1": "a.x"} and state["refs_url"] == "https://e.test/b"
    data = json.loads(invoke("goto", "https://e.test/b", "--snapshot", "--json").stdout)
    assert data["snapshot"]["items"][0]["ref"] == 1


def test_goto_snapshot_reports_settled_url(fake, invoke):
    """--snapshot waits for a redirect the page starts before url/navigated are read."""
    fake.page.evaluate_result = SNAP
    fake.page.navigates = ("https://e.test/after", 0.05)
    result = invoke("goto", "https://e.test/b", "-s")
    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "url: https://e.test/after"
    assert "navigated: true" in lines
    assert config.load_state("S1")["refs_url"] == "https://e.test/after"


def test_back_forward_reload(fake, invoke):
    assert (
        invoke("back").stdout == "url: https://e.test/prev\ntitle: E\nnavigated: true\n"
    )
    assert fake.page.called("wait_for_load_state")[0][1] == ("load",)
    result = invoke("forward")
    assert result.exit_code == 1 and "no further history" in result.stderr
    assert invoke("reload", "--wait-until", "domcontentloaded").exit_code == 0
    assert fake.page.called("reload")[0][2] == {
        "wait_until": "domcontentloaded",
        "timeout": 30.0,
    }


def test_snapshot_command(fake, invoke):
    fake.page.evaluate_result = SNAP
    result = invoke("snapshot", "--limit", "10", "--find", "x")
    assert result.exit_code == 0, result.stderr
    assert result.stdout.splitlines() == [
        "url: https://e.test/  title: E",
        '[@1] link "x" href=https://e.test/x',
    ]
    assert fake.page.called("evaluate")[0][1][1:] == (10, False, "x")
    assert config.load_state("S1")["refs"] == {"1": "a.x"}
    data = json.loads(invoke("snapshot", "-i", "--json").stdout)
    assert data["ok"] and data["total"] == 1 and data["url"] == "https://e.test/"
    assert fake.page.called("evaluate")[1][1][1:] == (500, True, None)


def test_dialogs_are_reported(fake, invoke, monkeypatch):
    def with_dialog(action):
        async def wrapped(a):
            a.dialogs.append({"kind": "confirm", "message": "sure?", "accepted": False})
            return await action(a)

        return wrapped

    original = page_cmd.act
    monkeypatch.setattr(
        page_cmd, "act", lambda s, action, **kw: original(s, with_dialog(action), **kw)
    )
    result = invoke("reload")
    assert result.stderr == 'dialog: confirm "sure?" dismissed\n'
    assert "dialogs" not in result.stdout
    data = json.loads(invoke("reload", "--json").stdout)
    assert data["dialogs"] == [{"kind": "confirm", "message": "sure?", "accepted": False}]
    data = json.loads(invoke("tab", "list", "--json").stdout)
    assert data["dialogs"] == [{"kind": "confirm", "message": "sure?", "accepted": False}]
    assert isinstance(data["tabs"], list)


def test_tabs(fake, invoke):
    rows = json.loads(invoke("tab", "list", "--json").stdout)["tabs"]
    assert rows == [
        {"index": 0, "id": "T1", "active": True, "url": "https://e.test/", "title": "E"}
    ]
    assert invoke("tab", "list").stdout.splitlines()[0] == "index: 0"
    assert config.load_state("S1")["tabs"] == ["T1"]
    created = json.loads(invoke("tab", "new", "e.test/2", "--json").stdout)
    assert created["id"] == "T2" and config.load_state("S1")["target_id"] == "T2"
    assert fake.browser.pages[1].called("goto")[0][1] == ("https://e.test/2",)
    fake.browser.pages.reverse()  # Chrome's order changed: numbers still follow the printed list
    assert invoke("tab", "switch", "0").exit_code == 0
    assert config.load_state("S1")["target_id"] == "T1" and fake.page.called(
        "bring_to_front"
    )
    assert invoke("tab", "close", "T2").exit_code == 0 and fake.browser.pages[0].called(
        "close"
    )
    invoke("tab", "close")  # the session's own page goes through browser-level CDP
    assert fake.browser.cdp.called("send")[0][1] == (
        "Target.closeTarget",
        {"targetId": "T1"},
    )
    assert config.load_state("S1")["target_id"] is None
    assert invoke("tab", "switch", "9").exit_code == 1


GO = {"ref": 7, "role": "button", "name": "Go", "selector": "#go"}


def test_refs_survive_a_filtered_snapshot_of_the_same_page(fake, invoke):
    fake.page.evaluate_result = {"items": [SNAP["items"][0], GO], "total": 2}
    assert invoke("snapshot").exit_code == 0
    fake.page.evaluate_result = {"items": [GO], "total": 1}
    assert invoke("snapshot", "--find", "go").exit_code == 0
    fake.page.evaluate_result = {"items": [], "total": 0}
    assert invoke("snapshot", "--find", "nothing").exit_code == 0
    fake.page.evaluate_result = {"items": [SNAP["items"][0], GO], "total": 2}
    for ref, css in (("@1", "a.x"), ("@7", "#go")):
        result = invoke("click", ref)
        assert result.exit_code == 0, result.stderr
        assert fake.page.called("click")[-1][1] == (css,)


def test_snapshot_of_another_url_or_tab_replaces_refs(fake, invoke):
    fake.page.evaluate_result = {"items": [GO], "total": 1}
    fake.page._url = "https://e.test/other"
    assert invoke("snapshot").exit_code == 0
    assert config.load_state("S1")["refs"] == {"7": "#go"}
    fake.page.target_id = "T2"
    fake.page.evaluate_result = SNAP
    assert invoke("snapshot").exit_code == 0
    assert config.load_state("S1")["refs"] == {"1": "a.x"}
    result = invoke("click", "@7")
    assert result.exit_code == 6 and "unknown ref @7" in result.stderr


def test_snapshot_attached_to_an_action_replaces_refs(fake, invoke):
    fake.page.evaluate_result = {"items": [SNAP["items"][0], GO], "total": 2}
    assert invoke("snapshot").exit_code == 0
    fake.page.evaluate_result = SNAP  # the page after the action no longer lists @7
    assert invoke("goto", "https://e.test/", "-s").exit_code == 0
    assert config.load_state("S1")["refs"] == {"1": "a.x"}


def test_a_kept_ref_whose_element_changed_is_stale(fake, invoke):
    fake.page.evaluate_result = {"items": [GO], "total": 1}
    assert invoke("snapshot").exit_code == 0
    assert invoke("click", "@7").exit_code == 0
    # the page re-rendered: the saved selector now finds another element
    fake.page.evaluate_result = {"items": [{**GO, "name": "Delete account"}], "total": 1}
    result = invoke("click", "@7")
    assert result.exit_code == 6
    assert "error [stale_ref]: @7 changed since the snapshot" in result.stderr
    assert len(fake.page.called("click")) == 1
    fake.page.evaluate_result = {"items": [], "total": 0}  # now hidden
    assert invoke("click", "@7").exit_code == 6
