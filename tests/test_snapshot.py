import asyncio

from surfsky_cli import snapshot

ITEMS = [
    {
        "ref": 1,
        "role": "heading",
        "name": "Example Domain",
        "selector": "body > h1",
        "level": 1,
    },
    {
        "ref": 2,
        "role": "link",
        "name": "More information...",
        "selector": "body > p:nth-of-type(2) > a",
        "href": "https://www.iana.org/domains/example",
    },
    {
        "ref": 3,
        "role": "textbox",
        "name": "Search",
        "selector": "#q",
        "input_name": "q",
        "type": "search",
    },
    {
        "ref": 4,
        "role": "checkbox",
        "name": "Remember me",
        "selector": "#r",
        "checked": False,
    },
]
UNREACHABLE = [
    {"kind": "iframe", "src": "https://pay.test/frame", "selector": "body > iframe"}
]
DATA = {
    "url": "https://example.com/",
    "title": "Example Domain",
    "items": ITEMS,
    "total": 6,
    "unreachable": UNREACHABLE,
}


def test_render():
    assert snapshot.render(DATA).splitlines() == [
        "url: https://example.com/  title: Example Domain",
        '[@1] heading "Example Domain" (h1)',
        '[@2] link "More information..." href=https://www.iana.org/domains/example',
        '[@3] textbox "Search" type=search input_name=q',
        '[@4] checkbox "Remember me" checked=false',
        "[--] iframe src=https://pay.test/frame (content not reachable)",
        "(2 more; raise --limit)",
    ]


def test_script_shape():
    assert snapshot.SCRIPT.startswith("(limit, interactive, find) =>")
    assert "getFullAXTree" not in snapshot.SCRIPT  # a DOM walker in the isolated world
    assert "shadowRoot" in snapshot.SCRIPT and "iframe" in snapshot.SCRIPT


def test_save_refs():
    state = {}
    snapshot.save_refs(state, "T1", "https://example.com/", DATA)
    assert state == {
        "refs": {
            "1": "body > h1",
            "2": "body > p:nth-of-type(2) > a",
            "3": "#q",
            "4": "#r",
        },
        "refs_target_id": "T1",
        "refs_url": "https://example.com/",
        "unreachable": 1,
    }


class Page:
    def __init__(self):
        self.calls = []

    async def evaluate(self, expression, *args, **kwargs):
        self.calls.append(("evaluate", args))
        return DATA

    async def wait_for_load_state(self, state, *, timeout):
        self.calls.append(("load", state, timeout))


def test_take_and_after_action():
    page = Page()
    assert (
        asyncio.run(snapshot.take(page, limit=10, interactive=True, find="more")) is DATA
    )
    assert page.calls[-1] == ("evaluate", (10, True, "more"))
    assert asyncio.run(snapshot.after_action(page)) is DATA
    assert ("load", "load", 10.0) in page.calls
