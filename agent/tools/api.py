"""Acme API tools, generated from the endpoint catalog `acme/knowledge/api.yaml` (D-107).

`load_catalog()` reads and validates the catalog; `api_tools(client)` turns every entry into a ToolSpec whose
`request_of` gives the real method and path, so the gate sees exactly what will be sent. No Acme path is written
in agent/ code: every one comes from the catalog (an isolation test refuses an API path literal in agent/).

`AcmeClient` is one run's HTTP session: httpx, its own cookie jar, a login with the agent's credentials from
config (never a tool argument, so never in the LLM context, register 3.4). Failures are typed: the client's own
timeout becomes `timeout` (registry._run only catches the built-in TimeoutError, N.132), a transport failure
`connection_error`, and Acme's typed errors pass through unchanged.

Retries (register 3.5, 3.4): at most one per call, and only after a failure that leaves the outcome unknown
(timeout, connection error, 5xx) or a lost session. Acme's business refusals (4xx) are never retried (N.133).
- a read: on a lost session, log in again and retry once;
- a write with an idempotency key: retry with the same key (derived from run_id + call fingerprint, so it is
  stable across retries and across calls); Acme replays the stored result if the first attempt committed;
- a write without one: read back first (the catalog's `read_back`); if the write already happened, return that
  row with `already_done: true`, else retry. A failed read-back means no retry, ever.
A keyless write whose outcome is still unknown is remembered per (run, fingerprint) with the ids that existed
before it, so the next identical call reads back before writing again (N.130).
"""

import hashlib
import string
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote, unquote

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, model_validator

from agent.policy.gate import HttpRequest, SideEffect, Target
from agent.tools.files import scratch_dir
from agent.tools.registry import ACME_ERROR_TYPES, RunContext, ToolResult, ToolSpec, fingerprint

CATALOG_PATH = Path(__file__).resolve().parents[2] / "acme" / "knowledge" / "api.yaml"
DEFAULT_TIMEOUT_SECONDS = 20.0
UNKNOWN_OUTCOME = frozenset({"timeout", "connection_error", "server_error"})
SESSION_LOST = frozenset({"session_expired", "login_required"})
ARG_TYPES: dict[str, type] = {"string": str, "integer": int, "date": date, "boolean": bool}
TRANSPORT_ARGS = {"idempotency_key": "Leave empty: the runtime derives one key per intended write"}
# What a tool reads or writes (D-131): the verifier matches audit rows to writes by it, and the gate's run facts
# use it to tell business records (trusted when read, D-133) from mail, audit rows and files.
Entity = Literal["vendor", "invoice", "approval", "payment", "employee", "it_ticket", "mail", "audit", "file"]


# --- the catalog ----------------------------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Arg(_Strict):
    type: Literal["string", "integer", "date", "boolean", "strings"]
    description: str = Field(min_length=1)
    required: bool = True
    enum: list[str] | None = None
    pattern: str | None = None


class Undo(_Strict):
    tool: str
    args: dict[str, str]                      # undo argument <- field of this tool's result


class ReadBack(_Strict):
    kind: Literal["new_row", "target_state"]
    tool: str
    args: dict[str, str] = {}                 # read-tool argument <- this call's argument
    match: dict[str, str] = {}                # row field <- this call's argument
    expect: dict[str, str | int] = {}         # row field = literal; "$user" is the agent's login


class Endpoint(_Strict):
    name: str
    description: str
    method: Literal["GET", "POST"]
    path: str
    side_effect: SideEffect
    entity: Entity
    args: dict[str, Arg] = {}
    trust_sensitive_args: list[str] = []      # payee, bank details, vendor identity, recipients, amounts (D-131)
    undo: Undo | None = None
    no_undo_reason: str | None = None
    transport_args: list[Literal["idempotency_key"]] = []
    sensitive_args: list[str] = []
    read_back: ReadBack | None = None
    response: Literal["json", "file"] = "json"
    untrusted: str | None = None              # provenance origin of returned text, e.g. "mail:{mail_id}"

    @property
    def path_params(self) -> list[str]:
        return [field for _, field, _, _ in string.Formatter().parse(self.path) if field]


class Session(_Strict):
    api_prefix: str                           # every tool path lives under it (an allowlist: no admin route fits)
    login_method: Literal["POST"]
    login_path: str
    user: str
    password_key: str
    idempotency_header: str
    replay_header: str
    login_page: str                           # where the browser lands when its session is gone
    creator_fields: list[str]                 # row fields naming who created it; the agent's own rows are never
                                              # trusted evidence (D-133)


class UiForm(_Strict):
    path: str                                 # the form's action, {x} = one path segment
    side_effect: SideEffect
    same_as: str | None = None                # the API tool that makes the same write
    trust_sensitive_args: list[str] = []      # form fields the gate treats as trust-sensitive (D-125)

    def matches(self, path: str) -> bool:
        mine, theirs = self.path.strip("/").split("/"), path.strip("/").split("/")
        return len(mine) == len(theirs) and all(m == t or m.startswith("{") for m, t in zip(mine, theirs))


class Catalog(_Strict):
    schema_version: Literal[0]
    session: Session
    tools: list[Endpoint]
    ui_forms: list[UiForm] = []

    def get(self, name: str) -> Endpoint | None:
        return next((ep for ep in self.tools if ep.name == name), None)

    def form(self, path: str) -> UiForm | None:
        return next((f for f in self.ui_forms if f.matches(path)), None)

    def form_effect(self, path: str) -> SideEffect:
        """What submitting a form to `path` does; a form the catalog does not know is an irreversible write."""
        form = self.form(path)
        return form.side_effect if form else "irreversible_write"

    @model_validator(mode="after")
    def _consistent(self) -> "Catalog":
        names = [ep.name for ep in self.tools]
        problems = [f"{n}: duplicate tool name" for n in sorted({n for n in names if names.count(n) > 1})]
        for ep in self.tools:
            problems += [f"{ep.name}: {p}" for p in _problems(ep, self)]
        problems += _path_problems(self.session.login_path, self.session.api_prefix)
        for form in self.ui_forms:
            twin = self.get(form.same_as) if form.same_as else None
            if form.path.startswith(self.session.api_prefix) or not form.path.startswith("/"):
                problems.append(f"ui form {form.path!r} must be a page path outside the API prefix")
            if form.same_as and (twin is None or twin.side_effect != form.side_effect):
                problems.append(f"ui form {form.path!r}: same_as {form.same_as!r} is not a tool with the same side effect")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def undo_call(self, tool: str, result: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
        """The compensating call for one successful write: (undo tool, its args from the write's result)."""
        ep = self.get(tool)
        if ep is None or ep.undo is None:
            return None
        return ep.undo.tool, {arg: result[field] for arg, field in ep.undo.args.items()}


def _path_problems(path: str, prefix: str) -> list[str]:
    plain = unquote(path)
    if "//" in plain or "/../" in plain + "/" or "/./" in plain + "/" or "%" in path:
        return [f"path {path!r} must be normalised, without encoded characters"]
    return [] if path.startswith(prefix) else [f"path {path!r} is outside the API prefix {prefix!r}"]


def _problems(ep: Endpoint, catalog: Catalog) -> list[str]:
    problems = _path_problems(ep.path, catalog.session.api_prefix)
    for param in ep.path_params:
        arg = ep.args.get(param)
        if arg is None or not arg.required or arg.type not in ("string", "integer"):
            problems.append(f"path parameter {param!r} must be a required string or integer argument")
    for name, arg in ep.args.items():
        if arg.enum and arg.type != "string" or arg.pattern and arg.type not in ("string", "strings"):
            problems.append(f"argument {name!r}: enum needs type string, pattern string or strings")
    problems += [f"sensitive arg {a!r} is not an argument" for a in ep.sensitive_args if a not in ep.args]
    problems += [f"trust-sensitive arg {a!r} is not an argument" for a in ep.trust_sensitive_args if a not in ep.args]
    problems += [f"transport arg {a!r} clashes with an argument" for a in ep.transport_args if a in ep.args]
    if ep.untrusted:
        problems += [f"untrusted origin names {f!r}, not an argument"
                     for _, f, _, _ in string.Formatter().parse(ep.untrusted) if f and f not in ep.args]
    if ep.side_effect == "read":
        if ep.method != "GET" or ep.undo or ep.no_undo_reason or ep.read_back or ep.transport_args:
            problems.append("a read is a GET with no undo, read_back or transport args")
        return problems
    if ep.method != "POST" or ep.response != "json":
        problems.append("a write is a POST with a JSON response")
    if (ep.side_effect == "reversible_write") != (ep.undo is not None) or (ep.undo is None) == (ep.no_undo_reason is None):
        problems.append("a reversible write names its undo; any other write gives no_undo_reason instead")
    if ep.undo:
        target = catalog.get(ep.undo.tool)
        if target is None or target.side_effect == "read":
            problems.append(f"undo {ep.undo.tool!r} is not a write tool in the catalog")
        else:
            problems += [f"undo argument {a!r} is not an argument of {target.name}"
                         for a in ep.undo.args if a not in target.args]
    if "idempotency_key" not in ep.transport_args and ep.read_back is None:
        problems.append("a write without an idempotency key needs a read_back (register 3.5)")
    if ep.read_back:
        rb, reader = ep.read_back, catalog.get(ep.read_back.tool)
        if reader is None or reader.side_effect != "read":
            problems.append(f"read_back tool {rb.tool!r} is not a read tool in the catalog")
        else:
            problems += [f"read_back argument {a!r} is not an argument of {reader.name}"
                         for a in rb.args if a not in reader.args]
        problems += [f"read_back refers to {a!r}, not an argument" for a in [*rb.args.values(), *rb.match.values()]
                     if a not in ep.args]
    return problems


class CatalogError(ValueError):
    """The endpoint catalog is unreadable or inconsistent. Raised at load time, never during a run."""


def load_catalog(path: Path | str = CATALOG_PATH) -> Catalog:
    try:
        return Catalog.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise CatalogError(f"endpoint catalog {path}: {exc}") from exc


def args_model(ep: Endpoint) -> type[BaseModel]:
    """The tool's strict argument model; its JSON schema is what the LLM sees."""
    fields: dict[str, Any] = {}
    for name, arg in ep.args.items():
        if arg.type == "strings":
            kind: Any = list[Annotated[str, Field(pattern=arg.pattern)]] if arg.pattern else list[str]
        else:
            kind = Literal[tuple(arg.enum)] if arg.enum else ARG_TYPES[arg.type]
        extra = {"pattern": arg.pattern} if arg.pattern and arg.type == "string" else {}
        fields[name] = ((kind, Field(description=arg.description, **extra)) if arg.required
                        else (kind | None, Field(None, description=arg.description, **extra)))
    for name in ep.transport_args:
        fields[name] = (str | None, Field(None, min_length=1, max_length=200, description=TRANSPORT_ARGS[name]))
    title = "".join(part.title() for part in ep.name.split("_")) + "Args"
    return create_model(title, __config__=ConfigDict(extra="forbid"), **fields)


def _parts(ep: Endpoint, args: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """(path with its parameters filled in, the remaining non-empty business args)."""
    path = ep.path.format(**{p: quote(str(args[p]), safe="") for p in ep.path_params})
    rest = {k: v for k, v in args.items() if v is not None and k not in ep.path_params and k not in ep.transport_args}
    return path, rest


# --- the HTTP session -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Reply:
    result: ToolResult
    content: bytes = b""
    replayed: bool = False


def _typed(response: httpx.Response) -> ToolResult:
    if response.is_success and not response.headers.get("content-type", "").startswith("application/json"):
        return ToolResult(ok=True)  # a file: the bytes travel in Reply.content
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and body.get("ok") is True and isinstance(body.get("data"), dict):
        return ToolResult(ok=True, detail=str(body.get("detail") or ""), data=body["data"])
    if isinstance(body, dict) and body.get("error_type") in ACME_ERROR_TYPES:  # passed through unchanged
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        return ToolResult(ok=False, error_type=body["error_type"], detail=str(body.get("detail", "")),
                          data={**data, "http_status": response.status_code})
    kind = "server_error" if response.status_code >= 500 else "invalid_request"
    return ToolResult.fail(kind, f"HTTP {response.status_code} without Acme's typed body", http_status=response.status_code)


def _same(value: Any, wanted: Any) -> bool:
    if isinstance(value, str) and isinstance(wanted, str):
        return value.casefold() == wanted.casefold()
    return value == wanted


def _done(row: Mapping[str, Any], already: bool, attempts: list[str], detail: str = "") -> ToolResult:
    detail = detail or ("already done: " + attempts[-1] if already else "done")
    return ToolResult(ok=True, detail=detail, data={**row, "already_done": already, "attempts": attempts})


class AcmeClient:
    """One run's session with Acme. Creating it does no I/O; it logs in on first use (one client per run: the
    httpx client belongs to the event loop that first used it, N.135)."""

    def __init__(self, config: Mapping[str, str], catalog: Catalog, transport: httpx.AsyncBaseTransport | None = None):
        self.catalog = catalog
        self.session = catalog.session
        self.base_url = config.get("ACME_URL", "")
        self.timeout = float(config.get("ACME_HTTP_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS)
        self._password = config.get(catalog.session.password_key, "")
        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        self._logged_in = False
        self._unresolved: dict[tuple[str, str], set[int]] = {}  # (run, fingerprint) -> ids before the write

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
        self._http, self._logged_in = None, False

    async def _send(self, method: str, path: str, *, query: Mapping[str, Any] | None = None,
                    body: Mapping[str, Any] | None = None, headers: Mapping[str, str] | None = None) -> Reply:
        if not self.base_url:
            return Reply(ToolResult.fail("connection_error", "ACME_URL is not configured"))
        if self._http is None:
            self._http = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, transport=self._transport)
        try:
            response = await self._http.request(method, path, params=query, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            return Reply(ToolResult.fail("timeout", f"{method} {path}: no response within {self.timeout:g} s "
                                                    f"({type(exc).__name__}); the outcome is unknown"))
        except httpx.TransportError as exc:
            return Reply(ToolResult.fail("connection_error", f"{method} {path}: {type(exc).__name__}: {exc}"))
        replayed = response.headers.get(self.session.replay_header, "").lower() == "true"
        return Reply(_typed(response), response.content, replayed)

    def login_body(self) -> dict[str, str]:
        """The agent's login form, for this client and the run's browser session; never logged, never a tool arg."""
        return {"username": self.session.user, "password": self._password}

    async def login(self) -> ToolResult:
        if not self._password:
            return ToolResult.fail("invalid_credentials", f"{self.session.password_key} is not set in the agent config")
        reply = await self._send(self.session.login_method, self.session.login_path, body=self.login_body())
        self._logged_in = reply.result.ok
        return reply.result

    async def _authed(self, method: str, path: str, **kwargs: Any) -> Reply:
        if not self._logged_in:
            login = await self.login()
            if not login.ok:
                return Reply(login)
        return await self._send(method, path, **kwargs)

    async def read(self, ep: Endpoint, args: Mapping[str, Any]) -> Reply:
        path, query = _parts(ep, args)
        reply = await self._authed(ep.method, path, query=query)
        if reply.result.error_type in SESSION_LOST:  # reads are safe to repeat: one re-login, one retry
            login = await self.login()
            reply = await self._send(ep.method, path, query=query) if login.ok else Reply(login)
        return reply

    async def read_tool(self, ep: Endpoint, args: Mapping[str, Any], ctx: RunContext) -> ToolResult:
        reply = await self.read(ep, args)
        result = reply.result
        if not result.ok:
            return result
        if ep.response == "file":
            name = str(args["name"])
            target = scratch_dir(ctx) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(reply.content)
            return ToolResult(ok=True, detail=f"saved {name} ({len(reply.content)} bytes) for extract_pdf_text",
                              data={"name": name, "bytes": len(reply.content),
                                    "sha256": hashlib.sha256(reply.content).hexdigest()})
        if ep.untrusted:  # text written by outsiders: data, never instructions (register 4.7)
            origin = ep.untrusted.format(**args)
            return result.model_copy(update={"data": {**result.data,
                                                      "provenance": {"source": "untrusted", "origin": origin}}})
        return result

    async def _read_back(self, ep: Endpoint, args: Mapping[str, Any]) -> list[dict[str, Any]] | None:
        """Rows matching the write's business key, or None when the read itself failed."""
        rb = ep.read_back
        reader = self.catalog.get(rb.tool)
        reply = await self.read(reader, {k: args[v] for k, v in rb.args.items()})
        if not reply.result.ok:
            return None
        data = reply.result.data
        rows = data["items"] if isinstance(data.get("items"), list) else [data]
        wanted = {field: args[arg] for field, arg in rb.match.items()}
        wanted |= {field: self.session.user if value == "$user" else value for field, value in rb.expect.items()}
        return [row for row in rows if all(_same(row.get(f), v) for f, v in wanted.items())]

    async def write(self, ep: Endpoint, args: Mapping[str, Any], ctx: RunContext) -> ToolResult:
        path, body = _parts(ep, args)
        call = fingerprint(ep.name, dict(args), tuple(ep.transport_args))
        memo, attempts, before = (ctx.run_id, call), [], set()
        headers = {}
        if "idempotency_key" in ep.transport_args:
            key = args.get("idempotency_key") or hashlib.sha256(f"{ctx.run_id}:{call}".encode()).hexdigest()[:40]
            headers[self.session.idempotency_header] = key
        if ep.read_back:  # read first: a target state already reached, or the ids that exist before we write
            rows = await self._read_back(ep, args)
            if rows is None:
                return ToolResult.fail("connection_error", f"could not read back before {ep.name}; nothing written")
            if ep.read_back.kind == "target_state" and rows:
                return _done(rows[0], True, ["already in the target state before writing"])
            before = self._unresolved.get(memo, {row["id"] for row in rows})
            ours = [row for row in rows if row["id"] not in before]
            if ours:
                self._unresolved.pop(memo, None)
                return _done(ours[0], True, ["an earlier call's write had committed"])

        for attempt in (1, 2):
            reply = await self._authed(ep.method, path, body=body or None, headers=headers)
            result = reply.result
            attempts.append(f"attempt {attempt}: " + ("replayed by Acme" if reply.replayed else
                                                      "ok" if result.ok else str(result.error_type)))
            if result.ok:
                self._unresolved.pop(memo, None)
                return _done(result.data, reply.replayed, attempts, result.detail)
            if result.error_type in SESSION_LOST and attempt == 1:
                login = await self.login()
                if not login.ok:
                    return login
                attempts.append("logged in again")
            elif result.error_type not in UNKNOWN_OUTCOME:
                self._unresolved.pop(memo, None)
                return result  # Acme refused and rolled back (or the session is lost again): passed through
            elif ep.read_back and ep.read_back.kind == "new_row":
                self._unresolved[memo] = before
            if attempt == 2:
                break
            if ep.read_back:  # without a key, read back before the retry (register 3.5)
                rows = await self._read_back(ep, args)
                if rows is None:
                    attempts.append("read-back failed; not retried")
                    break
                ours = rows if ep.read_back.kind == "target_state" else [r for r in rows if r["id"] not in before]
                if ours:
                    self._unresolved.pop(memo, None)
                    return _done(ours[0], True, attempts + [f"read-back found {ep.read_back.tool} row {ours[0]['id']}"])
                attempts.append("read-back: not written; retrying")
        unknown = result.error_type in UNKNOWN_OUTCOME
        note = "; the outcome is unknown, read back before writing again" if unknown else ""
        return ToolResult(ok=False, error_type=result.error_type, detail=result.detail + note,
                          data={**result.data, "outcome_unknown": unknown, "attempts": attempts})


def api_tools(client: AcmeClient) -> list[ToolSpec]:
    return [_spec(ep, client) for ep in client.catalog.tools]


def _spec(ep: Endpoint, client: AcmeClient) -> ToolSpec:
    async def fn(args: BaseModel, ctx: RunContext) -> ToolResult:
        clean = args.model_dump(mode="json")  # the same values the registry fingerprinted
        if ep.side_effect == "read":
            return await client.read_tool(ep, clean, ctx)
        return await client.write(ep, clean, ctx)

    def request_of(args: BaseModel) -> HttpRequest:
        return HttpRequest(method=ep.method, path=_parts(ep, args.model_dump(mode="json"))[0])

    def target_of(args: BaseModel) -> Target | None:
        """The existing record a write changes: its entity and the one integer id in its path (undo tools)."""
        ids = [p for p in ep.path_params if ep.args[p].type == "integer"]
        if ep.side_effect == "read" or len(ids) != 1:
            return None
        return Target(entity=ep.entity, id=getattr(args, ids[0]))

    return ToolSpec(name=ep.name, description=ep.description, args_model=args_model(ep), side_effect=ep.side_effect,
                    channel="api", fn=fn, undo=ep.undo.tool if ep.undo else None, no_undo_reason=ep.no_undo_reason,
                    sensitive_args=tuple(ep.sensitive_args), transport_args=tuple(ep.transport_args),
                    trust_sensitive_args=tuple(ep.trust_sensitive_args), request_of=request_of, target_of=target_of)
