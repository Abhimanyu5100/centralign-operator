"""Schema of acme/knowledge/policies.yaml. DRAFT until the Day 3 gate design (schema_version 0).

A rule says: when ALL of its conditions hold for a tool call, apply `effect`. The set of condition
types is fixed (D-017, extended by D-077); an unknown type, an unknown key or a wrong value type is a
load error, so a bad policy file fails closed. There is no `allow` effect: a rule can only deny or hold
a call for approval, so a user or task rule can never loosen an org rule (P.11). The defaults live in the
gate code by side-effect class, not here: reads are allowed, irreversible and external actions need
approval unless a rule says otherwise.

This module is data only. The evaluator (Day 3) reads these models; it does not live here.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, StringConstraints, field_validator, model_validator


class _Strict(BaseModel):
    # strict: no coercion (YAML `no` must not become the string "no"), no unknown keys
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


Name = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=60)]
Glob = Annotated[str, StringConstraints(pattern=r"^[/*]\S*$", max_length=200)]  # fnmatch glob; `*` also matches `/`
KnowledgeFile = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+\.yaml$")]  # bare name, no directories
DottedRef = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][\w]*(\.[A-Za-z_][\w]*)+$")]


# --- conditions: all of a rule's `when` list must hold -----------------------------------------------


class ToolIn(_Strict):
    """The call is one of these registry tools (names are checked against the registry from Day 2)."""
    type: Literal["tool_in"]
    tools: list[Name] = Field(min_length=1)


class RequestMatches(_Strict):
    """The call is an HTTP request whose method and path match. `method` is one verb or `*`; `path` is a
    glob (or a list of globs, any of which may match) in which `*` matches any characters including `/`."""
    type: Literal["request_matches"]
    method: Literal["*", "GET", "POST", "PUT", "PATCH", "DELETE"]
    path: Glob | Annotated[list[Glob], Field(min_length=1)]

    @property
    def paths(self) -> list[str]:
        return [self.path] if isinstance(self.path, str) else list(self.path)


class AmountGt(_Strict):
    """The call argument `arg` (an amount in paise, total including tax) is above `paise`."""
    type: Literal["amount_gt"]
    arg: Name
    paise: int = Field(gt=0)


class VendorStatusNotIn(_Strict):
    """The vendor named by the call argument `arg` has a status outside `statuses`."""
    type: Literal["vendor_status_not_in"]
    arg: Name
    statuses: list[Literal["approved", "pending", "blocked"]] = Field(min_length=1)


class RecipientDomainNotIn(_Strict):
    """The recipient in the call argument `arg` is outside the domains of `allowlist`, a file in
    acme/knowledge/. The gate keeps no domain list of its own (D-064)."""
    type: Literal["recipient_domain_not_in"]
    arg: Name
    allowlist: KnowledgeFile


class FieldSourceUntrusted(_Strict):
    """Any of the call arguments in `args` has a value that came only from untrusted text."""
    type: Literal["field_source_untrusted"]
    args: list[Name] = Field(min_length=1)


Condition = Annotated[
    ToolIn | RequestMatches | AmountGt | VendorStatusNotIn | RecipientDomainNotIn | FieldSourceUntrusted,
    Field(discriminator="type"),
]
CONDITION_TYPES = ("tool_in", "request_matches", "amount_gt", "vendor_status_not_in",
                   "recipient_domain_not_in", "field_source_untrusted")


# --- acme_check: how an `enforced_by: acme` rule is tied to a real check in Acme's code ----------------


class ConstantCheck(_Strict):
    """A constant in Acme's code has this value (e.g. the approval limit)."""
    kind: Literal["constant"]
    ref: DottedRef
    equals: int | str


class ActionCheck(_Strict):
    """An action in `acme.permissions.ACTION_ROLES` is allowed for exactly these roles."""
    kind: Literal["action"]
    ref: Annotated[str, StringConstraints(pattern=r"^[a-z_]+\.[a-z_]+$")]
    roles: list[Name] = Field(min_length=1)


class FunctionCheck(_Strict):
    """A function exists in Acme's code."""
    kind: Literal["function"]
    ref: DottedRef


class ModelCheck(_Strict):
    """An input model accepts exactly these fields and rejects any other."""
    kind: Literal["model"]
    ref: DottedRef
    fields: list[Name] = Field(min_length=1)


class NoRouteCheck(_Strict):
    """No route in Acme's app (any method) matches this glob."""
    kind: Literal["no_route"]
    path: Glob


AcmeCheck = Annotated[ConstantCheck | ActionCheck | FunctionCheck | ModelCheck | NoRouteCheck,
                      Field(discriminator="kind")]
LEVEL_PREFIX = {"org": "ORG", "user": "USR", "task": "TSK"}


class Rule(_Strict):
    id: str = Field(pattern=r"^(ORG|USR|TSK)-\d{3}$")
    level: Literal["org", "user", "task"]
    enforced_by: Literal["acme", "runtime"]
    effect: Literal["deny", "require_approval"]
    when: list[Condition] = Field(min_length=1)
    acme_check: list[AcmeCheck] = Field(default_factory=list)
    message: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def _consistent(self) -> "Rule":
        if not self.id.startswith(LEVEL_PREFIX[self.level] + "-"):
            raise ValueError(f"{self.id}: a {self.level} rule must have an id starting {LEVEL_PREFIX[self.level]}-")
        if self.enforced_by == "acme" and not self.acme_check:
            raise ValueError(f"{self.id}: enforced_by acme needs acme_check entries naming the Acme check")
        if self.enforced_by == "runtime" and self.acme_check:
            raise ValueError(f"{self.id}: only enforced_by acme rules carry acme_check")
        return self


class PolicyFile(_Strict):
    schema_version: Literal[0]
    rules: list[Rule] = Field(min_length=1)
    _allowlists: dict[str, frozenset[str]] = PrivateAttr(default_factory=dict)

    @field_validator("schema_version", mode="before")
    @classmethod
    def _plain_integer(cls, value):
        # Literal[0] alone also accepts False and 0.0, because Python says False == 0 == 0.0
        if type(value) is not int:
            raise ValueError("schema_version must be the integer 0")
        return value

    def attach_allowlists(self, domains: dict[str, frozenset[str]]) -> None:
        """Called once by the loader with the allowlist files it validated, so the gate uses exactly the
        domains that were checked at load time and never re-reads a file that may have changed."""
        self._allowlists.update(domains)

    def allowlist(self, name: str) -> frozenset[str]:
        try:
            return self._allowlists[name]
        except KeyError:
            raise KeyError(f"no rule names the allowlist {name!r}") from None

    @model_validator(mode="after")
    def _unique_ids(self) -> "PolicyFile":
        ids = [r.id for r in self.rules]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate rule ids: {', '.join(dupes)}")
        return self

