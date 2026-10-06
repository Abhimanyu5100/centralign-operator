"""Browser tools: Acme's pages through Playwright, the GUI channel (Day 2.3, D-117).

One Chromium browser context per run (its own cookies), launched with an explicit env from config, never the
inherited one (D-105), headless unless HEADED=1. A page is observed as a pruned accessibility view built from
Playwright's aria snapshot (role, accessible name, value, a short ref per control), never raw HTML. Actions find
their target by role and accessible name only (`get_by_role(role, name=..., exact=True).nth(k)`), never CSS or
XPath; nothing here names an Acme page: paths come from the caller and the endpoint catalog.

A click's side effect and request are read from the observed control before the gate decides (N.126): a link
reads (GET of its href); a submit button sends its form's method to its form's action, classified by the
catalog's `ui_forms` (an unknown form is an irreversible write). At click time the form target is read again and
a changed page refuses the click. Every navigation returns the page observed right after it, toasts and alerts
included (4.3). Landing on the login page means the session expired: the tool logs in again once over HTTP,
repeats a navigation once, and never resubmits a form (the caller reads back first, 3.4).
"""

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from playwright.async_api import Locator, Page, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeout
from pydantic import BaseModel, ConfigDict, Field

from agent.config import browser_env
from agent.policy.gate import HttpRequest, SideEffect
from agent.tools.api import AcmeClient
from agent.tools.registry import RunContext, ToolResult, ToolSpec

MAX_VIEW_CHARS, MAX_REFS, MAX_TEXT = 8000, 150, 400  # observation cap (N.127); every result says if it was cut
REF_PREFIX = {"link": "l", "button": "b", "textbox": "t", "searchbox": "t", "spinbutton": "t", "combobox": "c",
              "checkbox": "x", "radio": "r"}
DROPPED = {"document", "main", "table", "rowgroup", "rowheader", "cell", "columnheader", "list", "paragraph",
           "group", "generic", "/url", "option"}
STATUS_ERRORS = {400: "invalid_request", 401: "session_expired", 403: "forbidden", 404: "not_found",
                 409: "conflict", 415: "unsupported_media_type", 422: "invalid_input"}
_HEAD = re.compile(r'([/\w-]+)(?: "((?:[^"\\]|\\.)*)")?((?: \[[^\]]*\])*)')
FORM_TARGET = "e => e.form && e.type === 'submit' ? [e.form.method, e.form.getAttribute('action') || ''] : null"


@dataclass
class Element:
    ref: str
    role: str
    name: str
    nth: int                                  # among elements with this role and name, in page order
    value: str = ""
    href: str | None = None                   # a link's target path
    form: tuple[str, str] | None = None       # (METHOD, action path) a submit button sends


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return text[1:-1].replace('\\"', '"')
    return text


def parse_line(line: str) -> tuple[int, str, str, str, str] | None:
    """One aria-snapshot line -> (indent, role, name, attrs, value). Playwright writes YAML: an item whose text
    holds a colon is wrapped in single quotes ('row "a: b"':), and so may be a value."""
    stripped = line.lstrip(" ")
    if not stripped.startswith("- "):
        return None
    rest = stripped[2:]
    if rest.startswith("'"):  # a quoted key: find the closing quote ('' is an escaped quote)
        end = 1
        while end < len(rest) and not (rest[end] == "'" and rest[end + 1:end + 2] != "'"):
            end += 2 if rest[end] == "'" else 1
        head, rest = rest[1:end].replace("''", "'"), rest[end + 1:]
    else:
        m = _HEAD.match(rest)
        if m is None:
            return None
        head, rest = m[0], rest[m.end():]
    m = _HEAD.fullmatch(head)
    if m is None or (rest and not rest.startswith(":")):
        return None
    value = _unquote(rest[1:].strip()) if rest else ""
    return len(line) - len(stripped), m[1], (m[2] or "").replace('\\"', '"'), m[3], value


def _path(url: str) -> str:
    parts = urlparse(url)
    return parts.path + (f"?{parts.query}" if parts.query else "")


class BrowserSession:
    def __init__(self, client: AcmeClient, headed: bool = False):
        self.client, self.headed = client, headed
        self.elements: dict[str, Element] = {}  # refs from the latest observation
        self._pw = self._browser = self._context = self._page = None

    async def page(self) -> Page:
        if self._page is None:
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=not self.headed, env=browser_env())
            self._context = await self._browser.new_context(base_url=self.client.base_url)
            self._context.set_default_timeout(self.client.timeout * 1000)
            await self.login()
            self._page = await self._context.new_page()
        return self._page

    async def login(self) -> bool:
        response = await self._context.request.post(self.client.session.login_path, data=self.client.login_body())
        return response.ok

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()
        self._pw = self._browser = self._context = self._page = None

    def on_login_page(self) -> bool:
        return self._page is not None and urlparse(self._page.url).path == self.client.session.login_page

    def locator(self, element: Element) -> Locator:
        return self._page.get_by_role(element.role, name=element.name, exact=True).nth(element.nth)

    async def observe(self) -> dict[str, Any]:
        page = await self.page()
        lines, messages, elements, seen = [], [], {}, {}
        parsed = [parse_line(line) for line in (await page.aria_snapshot()).splitlines()]
        for i, item in enumerate(parsed):
            if not item:
                continue
            indent, role, name, attrs, value = item
            children = _children(parsed[i + 1:], indent)
            if role in REF_PREFIX and len(elements) < MAX_REFS:
                nth = seen.get((role, name), 0)
                seen[(role, name)] = nth + 1
                el = Element(f"{REF_PREFIX[role]}{len(elements) + 1}", role, name, nth, value)
                el.href = next((c[4] for c in children if c[1] == "/url"), None) if role == "link" else None
                options = [c[2] for c in children if c[1] == "option"]
                el.value = next((c[2] for c in children if c[1] == "option" and "selected" in c[3]), value) or value
                if role == "button":
                    target = await self.locator(el).evaluate(FORM_TARGET)
                    el.form = (target[0].upper(), urlparse(target[1]).path or urlparse(page.url).path) if target else None
                elements[el.ref] = el
                lines.append(_describe(el, options))
            elif role in ("status", "alert"):
                messages.append(f"{role}: {value or name}")
                lines.append(messages[-1])
            elif role not in DROPPED and (name or value):
                text = f'{role} "{name}"{attrs}' if name else f"{role}: {value[:MAX_TEXT]}"
                lines.append(text + (" ..." if len(value) > MAX_TEXT else ""))
        self.elements = elements
        view, truncated = "\n".join(lines), False
        if len(view) > MAX_VIEW_CHARS:
            view, truncated = view[:view.rfind("\n", 0, MAX_VIEW_CHARS)] + "\n... (view cut at the size cap)", True
        path = _path(page.url)
        return {"url": path, "title": await page.title(), "view": view, "messages": messages, "truncated": truncated,
                "elements": [{"ref": e.ref, "role": e.role, "name": e.name, "value": e.value,
                              "target": e.href or (" ".join(e.form) if e.form else None)} for e in elements.values()],
                "provenance": {"source": "untrusted", "origin": f"page:{path}"}}


def _children(items: list, indent: int) -> list:
    out = []
    for item in items:
        if item is None:
            continue
        if item[0] <= indent:
            break
        out.append(item)
    return out


def _describe(el: Element, options: list[str]) -> str:
    line = f'[{el.ref}] {el.role} "{el.name}"'
    if el.role in ("textbox", "searchbox", "spinbutton", "combobox"):
        line += f' = "{el.value}"'
    if options:
        line += " (options: " + " | ".join(options[:30]) + (" | ..." if len(options) > 30 else "") + ")"
    if el.href:
        line += f" -> {el.href}"
    if el.form:
        line += f" -> submits {el.form[0]} {el.form[1]}"
    return line


# --- the tools ---------------------------------------------------------------------------------------------------


class OpenArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(pattern=r"^/([^/\s\\][^\s\\]*)?$", description="A path on the company site, starting with /")


class RefArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str = Field(pattern=r"^[a-z]\d{1,3}$", description="A ref from the latest observation, e.g. b3")


class FillArgs(RefArgs):
    value: str = Field(max_length=5000, description="Text to type into the field (replaces its content)")


class SelectArgs(RefArgs):
    option: str = Field(description="The visible label of the option to choose")


def browser_tools(session: BrowserSession) -> list[ToolSpec]:
    catalog = session.client.catalog

    def target(args: RefArgs) -> Element | None:
        return session.elements.get(args.ref)

    def click_effect(args: RefArgs) -> SideEffect:
        el = target(args)
        if el is not None and (el.role == "link" or el.form and el.form[0] == "GET"):
            return "read"
        return catalog.form_effect(el.form[1]) if el is not None and el.form else "irreversible_write"

    def click_request(args: RefArgs) -> HttpRequest | None:
        el = target(args)
        if el is not None and el.href:
            return HttpRequest(method="GET", path=urlparse(el.href).path)
        return HttpRequest(method=el.form[0], path=el.form[1]) if el is not None and el.form else None

    async def navigated(response: Any, writes: bool, retry: Any) -> ToolResult:
        """Typed result of a navigation, with the page observed right after it; one re-login on a lost session."""
        renewed = session.on_login_page()
        if renewed:
            if not await session.login():
                return ToolResult.fail("invalid_credentials", "the session expired and logging in again failed")
            if writes:  # never resubmit a form: the caller reads back first (3.4)
                return ToolResult.fail("session_expired", "the session had expired; logged in again, the form was "
                                       "not submitted: read back, then repeat the click", session_renewed=True)
            response = await retry()
        status = await _first_status(response)
        page = await session.observe()
        page |= {"status": status, "session_renewed": renewed}
        if status is not None and status >= 400:
            kind = STATUS_ERRORS.get(status, "server_error" if status >= 500 else "invalid_request")
            return ToolResult(ok=False, error_type=kind, detail="; ".join(page["messages"]) or f"HTTP {status}",
                              data=page)
        return ToolResult(ok=True, detail="; ".join(page["messages"]) or page["title"], data=page)

    async def guarded(action: Any) -> ToolResult:
        try:
            return await action()
        except PlaywrightTimeout as exc:  # not the built-in TimeoutError (N.139)
            return ToolResult.fail("timeout", f"the page did not respond in time: {str(exc).splitlines()[0]}")

    async def resolve(args: RefArgs) -> tuple[Element, Locator] | ToolResult:
        el = target(args)
        if el is None or (await session.page() and await session.locator(el).count() == 0):
            return ToolResult.fail("not_found", f"no element {args.ref} on the page now; observe again")
        return el, session.locator(el)

    async def open_page(args: OpenArgs, ctx: RunContext) -> ToolResult:
        page = await session.page()
        return await guarded(lambda: _goto(page, args.path, navigated))

    async def observe(args: BaseModel, ctx: RunContext) -> ToolResult:
        page = await session.observe()
        return ToolResult(ok=True, detail=page["title"], data=page)

    async def click(args: RefArgs, ctx: RunContext) -> ToolResult:
        found = await resolve(args)
        if isinstance(found, ToolResult):
            return found
        el, loc = found
        if el.form and el.form[0] == "POST":
            now = await loc.evaluate(FORM_TARGET)
            if not now or (now[0].upper(), urlparse(now[1]).path or el.form[1]) != el.form:
                return ToolResult.fail("precondition_failed", f"{args.ref} no longer submits {' '.join(el.form)}; "
                                       "observe again (the gate decided on what the page showed)")
        if el.role != "link" and not el.form:  # e.g. a checkbox: no navigation to wait for
            failed = await guarded(loc.click)
            return failed if isinstance(failed, ToolResult) else await observe(args, ctx)
        page = session._page

        async def go() -> ToolResult:
            async with page.expect_navigation() as nav:
                await loc.click()
            return await navigated(await nav.value, writes,
                                   lambda: page.goto(parse_qs(urlparse(page.url).query).get("next", ["/"])[0]))
        writes = click_effect(args) != "read"
        result = await guarded(go)
        if writes and result.error_type == "timeout":  # the form may have been saved: read back first (3.5)
            result = result.model_copy(update={"data": {**result.data, "outcome_unknown": True}})
        return result

    async def fill(args: FillArgs, ctx: RunContext) -> ToolResult:
        found = await resolve(args)
        if isinstance(found, ToolResult):
            return found
        failed = await guarded(lambda: found[1].fill(args.value))
        if isinstance(failed, ToolResult):
            return failed
        return ToolResult(ok=True, detail=f"{args.ref} filled", data={"ref": args.ref, "value": args.value})

    async def select(args: SelectArgs, ctx: RunContext) -> ToolResult:
        found = await resolve(args)
        if isinstance(found, ToolResult):
            return found
        failed = await guarded(lambda: found[1].select_option(label=args.option))
        if isinstance(failed, ToolResult):
            return failed
        return ToolResult(ok=True, detail=f"{args.ref} set to {args.option}", data={"ref": args.ref, "option": args.option})

    class NoArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")

    return [
        ToolSpec(name="browser_open", description="Open a page of the company site in the browser and observe it.",
                 args_model=OpenArgs, side_effect="read", channel="gui", fn=open_page,
                 request_of=lambda a: HttpRequest(method="GET", path=urlparse(a.path).path)),
        ToolSpec(name="browser_observe", description="Observe the current page: controls with refs, text, messages.",
                 args_model=NoArgs, side_effect="read", channel="gui", fn=observe),
        ToolSpec(name="browser_click", description="Click a link or button by ref; a form submit may write.",
                 args_model=RefArgs, side_effect="irreversible_write", channel="gui", fn=click,
                 no_undo_reason="a form sent from the browser is undone, if at all, by the matching API undo tool",
                 side_effect_of=click_effect, request_of=click_request),
        ToolSpec(name="browser_fill", description="Type text into a text field by ref (nothing is sent until a submit).",
                 args_model=FillArgs, side_effect="read", channel="gui", fn=fill),
        ToolSpec(name="browser_select", description="Choose an option in a dropdown by ref and option label.",
                 args_model=SelectArgs, side_effect="read", channel="gui", fn=select),
    ]


async def _goto(page: Page, path: str, navigated: Any) -> ToolResult:
    return await navigated(await page.goto(path), False, lambda: page.goto(path))


async def _first_status(response: Any) -> int | None:
    """The status of the request the action itself sent (a POST answered 303 shows as the POST, not the GET)."""
    if response is None:
        return None
    request = response.request
    while request.redirected_from is not None:
        request = request.redirected_from
    first = await request.response()
    return first.status if first is not None else response.status
