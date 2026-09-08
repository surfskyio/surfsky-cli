import base64
import json

import pytest

from surfsky_cli.commands import scrape

HTML = (
    "<html><body><nav><a href='/n'>N</a></nav>"
    "<main><h1>Hi</h1><p>Text <a href='/x'>x</a></p></main></body></html>"
)


@pytest.fixture
def fetched(home, monkeypatch):
    seen = {}

    async def fetch(settings, url, **how):
        seen.update(how, url=url)
        return {
            "url": url or "https://cur.test/",
            "status": 200,
            "title": "Hi",
            "raw_html": HTML,
            "screenshot": b"\x89PNG" if how["want_shot"] else None,
        }

    monkeypatch.setattr(scrape, "fetch", fetch)
    return seen


def test_markdown_default(fetched, invoke):
    result = invoke("scrape", "https://e.test/")
    assert result.exit_code == 0, result.stderr
    assert result.stdout == "[N](/n)\n\n# Hi\n\nText [x](/x)\n"
    assert fetched["want_shot"] is False and fetched["wait_until"] == "load"


def test_current_page_without_url(fetched, invoke):
    data = json.loads(invoke("scrape", "-f", "links", "--json").stdout)
    assert fetched["url"] is None and data["url"] == "https://cur.test/"
    assert data["links"] == ["https://cur.test/n", "https://cur.test/x"]


def test_main_content_and_multi_format(fetched, invoke):
    data = json.loads(
        invoke(
            "scrape", "https://e.test/", "-f", "markdown,links", "--only-main-content"
        ).stdout
    )
    assert data["ok"] and data["markdown"] == "# Hi\n\nText [x](/x)\n"
    assert data["links"] == ["https://e.test/x"] and data["status"] == 200


def test_raw_html_and_screenshot_file(fetched, invoke, tmp_path):
    assert invoke("scrape", "https://e.test/", "-f", "raw_html").stdout == HTML + "\n"
    target = tmp_path / "shot.png"
    assert (
        invoke(
            "scrape", "https://e.test/", "-f", "screenshot", "-o", str(target)
        ).exit_code
        == 0
    )
    assert target.read_bytes() == b"\x89PNG"
    data = json.loads(
        invoke(
            "scrape", "https://e.test/", "--screenshot", "--full-page", "--json"
        ).stdout
    )
    assert base64.b64decode(data["screenshot"]) == b"\x89PNG" and "markdown" in data
    assert fetched["full_page"] is True


def test_unknown_format_is_usage_error(fetched, invoke):
    result = invoke("scrape", "https://e.test/", "-f", "pdf")
    assert result.exit_code == 2 and "pdf" in result.stderr


def test_scheme_is_added(fetched, invoke):
    invoke("scrape", "example.com", "--wait-for", "#done", "--profile", "P1")
    assert fetched["url"] == "https://example.com" and fetched["wait_for"] == "#done"
    assert fetched["profile"] == "P1" and fetched["keep"] is False
