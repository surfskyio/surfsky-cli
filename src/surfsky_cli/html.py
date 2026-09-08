import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from markdownify import ATX, markdownify

NOISE = "script, style, noscript, template, svg, iframe, title"
CHROME = (
    "nav, header, footer, aside, form, [aria-hidden=true], [role=navigation], "
    "[role=banner], [role=contentinfo], [role=complementary], [role=search]"
)
MAIN = "main, article, [role=main]"


def clean(html: str, *, main_content: bool = False) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    drop(soup, NOISE)
    if main_content:
        drop(soup, CHROME)
        if (root := soup.select_one(MAIN)) is not None:
            soup = BeautifulSoup(str(root), "html.parser")
    return soup


def drop(soup: BeautifulSoup, selector: str) -> None:
    for element in soup.select(selector):
        element.decompose()


def to_markdown(soup: BeautifulSoup) -> str:
    text = markdownify(str(soup), heading_style=ATX, bullets="-")
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def links(soup: BeautifulSoup, base_url: str) -> list[str]:
    found: dict[str, None] = {}  # insertion-ordered set
    for anchor in soup.select("a[href]"):
        href = urljoin(base_url, str(anchor["href"]).strip())
        if href.startswith(("http://", "https://")):
            found.setdefault(href, None)
    return list(found)
