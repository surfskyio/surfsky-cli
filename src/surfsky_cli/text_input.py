from contextlib import suppress
from typing import Any

import anyio
from surfsky import SurfskyError

REFOCUS_WAIT = 0.5

FIELD = r"""(selector, mark) => {
  const active = () => {
    let el = document.activeElement;
    while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement;
    return el;
  };
  const editable = el => el.isContentEditable || el.tagName === 'IFRAME'
    || el.matches('textarea, [role=textbox], [role=combobox], [role=searchbox], input:not([type=button],'
      + ' [type=submit], [type=reset], [type=checkbox], [type=radio], [type=file], [type=image],'
      + ' [type=range], [type=color])');
  if (mark) globalThis.__surfskyField = selector ? document.querySelector(selector) : active();
  const el = globalThis.__surfskyField;
  if (!el || !el.isConnected) return null;
  const value = el.matches('input, textarea') ? el.value : el.isContentEditable ? el.innerText : null;
  return {editable: editable(el), value, focused: active() === el};
}"""


async def enter(
    page: Any, css: str | None, text: str, target: str, replace: bool = False
) -> None:
    """Type into `css`, or into the focused element; repeated only when no key was sent."""
    before = await page.evaluate(FIELD, css, True)
    if css is None:
        if not (before and before["editable"]):
            raise ValueError(
                "no editable element has focus; type with the field as target"
            )
        await page.keyboard.type(text)
    else:
        send = page.fill if replace else page.type
        try:
            await send(css, text)
        except ValueError as exc:
            if "did not take focus" not in str(exc):
                raise
            await anyio.sleep(REFOCUS_WAIT)
            try:
                await send(css, text)
            except ValueError:
                raise ValueError(f"{target} did not take focus") from None
    after = None
    with suppress(SurfskyError):
        after = await page.evaluate(FIELD, css, False)
    if (
        text
        and before
        and after
        and isinstance(after["value"], str)
        and after["value"] == before["value"]
        and not after["focused"]
        and " ".join(text.split()) not in " ".join(after["value"].split())
    ):
        raise ValueError(
            "the page moved focus away while typing and the text did not arrive: "
            "a dialog may have opened"
        )
