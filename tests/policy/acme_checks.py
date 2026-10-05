"""Resolves an `acme_check` entry from policies.yaml against Acme's real code. A failure is an AssertionError
that says what is missing, so a renamed constant or a new bank route breaks a test, not production."""

import importlib

from acme import permissions
from agent.policy.models import ActionCheck, ConstantCheck, FunctionCheck, ModelCheck, NoRouteCheck
from agent.policy.pathglob import path_matches


def _resolve(ref: str):
    module_name, _, attr = ref.rpartition(".")
    try:
        return getattr(importlib.import_module(module_name), attr)
    except (ImportError, AttributeError) as exc:
        raise AssertionError(f"{ref} does not exist in Acme's code") from exc


def route_paths(app) -> list[str]:
    """Every path template of the app, including routes added through include_router (risk N.49)."""
    paths = set(app.openapi()["paths"])

    def leaves(routes):
        for r in routes:
            inner = getattr(r, "original_router", None)
            if inner is not None:
                yield from leaves(inner.routes)
            elif hasattr(r, "path"):
                yield r.path

    return sorted(paths | set(leaves(app.routes)))


def check(entry, app) -> None:
    if isinstance(entry, ConstantCheck):
        value = _resolve(entry.ref)
        assert value == entry.equals, f"{entry.ref} is {value!r}, the policy says {entry.equals!r}"
    elif isinstance(entry, FunctionCheck):
        assert callable(_resolve(entry.ref)), f"{entry.ref} is not callable"
    elif isinstance(entry, ActionCheck):
        roles = permissions.ACTION_ROLES.get(entry.ref)
        assert roles is not None, f"action {entry.ref} is not in ACTION_ROLES"
        assert roles == set(entry.roles), f"action {entry.ref} allows {sorted(roles)}, the policy says {sorted(entry.roles)}"
    elif isinstance(entry, ModelCheck):
        model = _resolve(entry.ref)
        assert set(model.model_fields) == set(entry.fields), (
            f"{entry.ref} has fields {sorted(model.model_fields)}, the policy says {sorted(entry.fields)}")
        assert model.model_config.get("extra") == "forbid", f"{entry.ref} must reject unknown fields"
    elif isinstance(entry, NoRouteCheck):
        hits = [p for p in route_paths(app) if path_matches(entry.path, p)]
        assert not hits, f"Acme serves routes matching {entry.path}: {hits}"
    else:  # pragma: no cover - the schema makes this unreachable
        raise AssertionError(f"unknown acme_check {entry!r}")
