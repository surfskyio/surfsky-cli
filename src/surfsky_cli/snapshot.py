import contextlib
import json
from typing import Any

import anyio
from surfsky import Page, SurfskyError

from .out import scalar

# Read the DOM in the SDK's isolated context; resolve refs through CSS selectors.
# ponytail: accessible names are approximated here; switch to
# Accessibility.getFullAXTree if agents misidentify elements.
SCRIPT = r"""(limit, interactive, find) => {
  const selector = 'a[href], button, input, select, textarea, summary, [role], '
    + '[contenteditable=""], [contenteditable="true"]'
    + (interactive ? '' : ', h1, h2, h3, h4, h5, h6');
  const INPUT_ROLES = {checkbox: 'checkbox', radio: 'radio', submit: 'button', button: 'button',
    reset: 'button', image: 'button', range: 'slider', file: 'file', search: 'searchbox'};
  const roleOf = el => {
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role');
    if (role) return role;
    if (/^h[1-6]$/.test(tag)) return 'heading';
    if (tag === 'a') return 'link';
    if (tag === 'button' || tag === 'summary') return 'button';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') return INPUT_ROLES[(el.type || 'text').toLowerCase()] || 'textbox';
    if (el.isContentEditable) return 'textbox';
    return tag;
  };
  const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 100);
  const nameOf = el => {
    const label = el.getAttribute('aria-label');
    if (label) return label.trim();
    const ids = el.getAttribute('aria-labelledby');
    if (ids) {
      const named = ids.split(/\s+/).map(id => document.getElementById(id)).filter(Boolean).map(text).join(' ').trim();
      if (named) return named;
    }
    if (el.labels && el.labels.length) return text(el.labels[0]);
    if (el.tagName === 'INPUT' && ['submit', 'button', 'reset'].includes(el.type)) return el.value;
    return el.placeholder || text(el) || el.title || el.alt || '';
  };
  const unique = id => document.querySelectorAll('#' + CSS.escape(id)).length === 1;
  const cssPath = el => {
    const parts = [];
    for (let node = el; node && node.nodeType === 1 && node !== document.documentElement; node = node.parentElement) {
      if (node.id && unique(node.id)) {
        parts.unshift('#' + CSS.escape(node.id));
        return parts.join(' > ');
      }
      let part = node.tagName.toLowerCase();
      const siblings = node.parentElement
        ? Array.from(node.parentElement.children).filter(s => s.tagName === node.tagName) : [];
      if (siblings.length > 1) part += ':nth-of-type(' + (siblings.indexOf(node) + 1) + ')';
      parts.unshift(part);
    }
    return parts.join(' > ');
  };
  const visible = el => {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return box.width > 0 && box.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const needle = (find || '').toLowerCase();
  const matches = item => !needle
    || [item.role, item.name, item.href || '', item.selector].join(' ').toLowerCase().includes(needle);
  const items = [];
  let ref = 0, total = 0;
  for (const el of document.querySelectorAll(selector)) {
    if ((el.tagName === 'INPUT' && el.type === 'hidden') || !visible(el)) continue;
    const roleAttr = el.getAttribute('role');
    if (roleAttr === 'presentation' || roleAttr === 'none') continue;
    ref++;  // Keep numbering stable when filtering with `find`.
    const role = roleOf(el);
    const item = {ref, role, name: nameOf(el), selector: cssPath(el)};
    if (/^H[1-6]$/.test(el.tagName)) item.level = Number(el.tagName[1]);
    if (el.tagName === 'A' && el.href) item.href = el.href;
    if (typeof el.name === 'string' && el.name) item.input_name = el.name;
    const field = ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)
      && !['submit', 'button', 'reset', 'checkbox', 'radio'].includes(el.type);
    if (field) {
      if (el.tagName === 'INPUT') item.type = el.type;
      if (el.value) item.value = String(el.value).slice(0, 100);
    }
    if (role === 'checkbox' || role === 'radio') item.checked = !!el.checked;
    if (el.tagName === 'SELECT') item.options = Array.from(el.options).slice(0, 20).map(o => o.value);
    if (el.disabled) item.disabled = true;
    if (!matches(item)) continue;
    total++;
    if (items.length < limit) items.push(item);
  }
  const unreachable = [];
  for (const frame of document.querySelectorAll('iframe')) {
    if (visible(frame)) unreachable.push({kind: 'iframe', src: frame.src || '', selector: cssPath(frame)});
  }
  for (const el of document.querySelectorAll('*')) {
    if (el.shadowRoot && visible(el)) unreachable.push({kind: 'shadow', tag: el.tagName.toLowerCase(), selector: cssPath(el)});
  }
  return {items, total, unreachable};
}"""

KEYS = ("href", "type", "input_name", "value", "checked", "options", "disabled")


async def take(
    page: Page, *, limit: int = 500, interactive: bool = False, find: str | None = None
) -> dict[str, Any]:
    return await page.evaluate(SCRIPT, limit, interactive, find)


def save_refs(
    state: dict[str, Any], target_id: str, url: str, data: dict[str, Any]
) -> None:
    state["refs"] = {str(item["ref"]): item["selector"] for item in data["items"]}
    state["refs_target_id"] = target_id
    state["refs_url"] = url
    state["unreachable"] = len(data.get("unreachable") or [])


def render_items(data: dict[str, Any]) -> str:
    lines = []
    for item in data["items"]:
        name = json.dumps(item.get("name", ""), ensure_ascii=False)
        head = f"[@{item['ref']}] {item['role']} {name}"
        if item.get("level"):
            head += f" (h{item['level']})"
        extra = " ".join(f"{key}={scalar(item[key])}" for key in KEYS if key in item)
        lines.append(f"{head} {extra}".rstrip())
    for block in data.get("unreachable") or []:
        what = (
            f"src={block['src']}"
            if block["kind"] == "iframe"
            else f"<{block['tag']}> shadow root"
        )
        lines.append(f"[--] {block['kind']} {what} (content not reachable)")
    missing = data["total"] - len(data["items"])
    if missing > 0:
        lines.append(f"({missing} more; raise --limit)")
    return "\n".join(lines)


def render(data: dict[str, Any]) -> str:
    return f"url: {data['url']}  title: {data['title']}\n" + render_items(data)


async def after_action(page: Page, *, limit: int = 500) -> dict[str, Any]:
    """Allow navigation to start before waiting for load and reading the DOM."""
    await anyio.sleep(0.3)
    # a page that never fires load still gets its snapshot
    with contextlib.suppress(SurfskyError):
        await page.wait_for_load_state("load", timeout=10.0)
    return await take(page, limit=limit)
