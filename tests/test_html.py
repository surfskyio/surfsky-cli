from surfsky_cli import html

PAGE = """<html><head><title>T</title><style>p{}</style><script>x()</script></head>
<body><nav><a href="/nav">Nav</a></nav>
<main><h1>Hello</h1><p>World <a href="/a">A</a> <a href="https://x.test/b">B</a>
<a href="/a">A again</a> <a href="mailto:x@y">mail</a></p></main>
<footer><a href="/foot">F</a></footer></body></html>"""


def test_markdown_everything():
    md = html.to_markdown(html.clean(PAGE))
    assert "# Hello" in md and "[Nav](/nav)" in md and "x()" not in md
    assert not md.startswith("\n") and md.endswith("\n")


def test_markdown_main_content_drops_chrome():
    md = html.to_markdown(html.clean(PAGE, main_content=True))
    assert md.startswith("# Hello")
    assert "/nav" not in md and "/foot" not in md


def test_links_absolute_deduped_http_only():
    assert html.links(html.clean(PAGE), "https://site.test/x/") == [
        "https://site.test/nav",
        "https://site.test/a",
        "https://x.test/b",
        "https://site.test/foot",
    ]


def test_title_never_leaks_into_markdown():
    bare = "<html><head><title>T</title></head><body><h1>Hello</h1></body></html>"
    for main_content in (False, True):  # no <main>: the whole document is kept
        assert html.to_markdown(html.clean(bare, main_content=main_content)) == "# Hello\n"
