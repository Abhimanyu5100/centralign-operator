"""Segment-aware path globs and path normalisation (D-088, risks N.83, N.101)."""

import pytest
from pydantic import ValidationError

from agent.policy.loader import load_policies
from agent.policy.models import RequestMatches
from agent.policy.pathglob import InvalidPath, check_glob, normalise_path, path_matches

RULES = {r.id: r for r in load_policies().rules}


def rule_matches(rule_id: str, raw_path: str) -> bool:
    cond = next(c for c in RULES[rule_id].when if isinstance(c, RequestMatches))
    return any(path_matches(p, raw_path) for p in cond.paths)


# --- the matcher ---------------------------------------------------------------------------------


@pytest.mark.parametrize("pattern, path, expected", [
    ("/approvals/*/decide", "/approvals/7/decide", True),
    ("/approvals/*/decide", "/approvals/7/x/decide", False),      # * never crosses a /
    ("/approvals/*/decide", "/x/approvals/7/decide", False),      # anchored at the start
    ("/approvals/*/decide", "/approvals/decide", False),          # * needs a segment
    ("/approvals/*/decide", "/approvals/7/decide/more", False),   # anchored at the end
    ("/a/**", "/a", True), ("/a/**", "/a/b/c/d", True), ("/a/**", "/ab", False),
    ("/**/*bank*/**", "/bank", True), ("/**/*bank*/**", "/api/vendors/4/bank", True),
    ("/**/*bank*/**", "/api/vendors/4/bank/x/y", True), ("/**/*bank*/**", "/api/vendors/4", False),
    ("/**", "/", True), ("/**", "/anything/at/all", True),
    ("/pre*fix", "/prexfix", True), ("/pre*fix", "/pre/fix", False),
    ("/a/*", "/a/b", True), ("/a/*", "/a/b/c", False), ("/a/*", "/a", False),
    ("/mail/", "/mail", True),                                    # a trailing slash on either side is the same
    ("/mail", "/mail/", True),
])
def test_glob_semantics(pattern, path, expected):
    assert path_matches(pattern, path) is expected


@pytest.mark.parametrize("pattern", [
    "api/x", "", "/a//b", "/a/./b", "/a/../b", "/a/b**", "/**x/b", "/a?b", "/a[b]", "/a{b}", "/a b", "/a\\b",
    "/a%5fb", "/a#b", "/ü",
])
def test_a_malformed_glob_is_a_load_error(pattern):
    with pytest.raises(ValueError):
        check_glob(pattern)


def test_a_policy_file_with_a_malformed_path_glob_fails_to_load():
    from tests.policy.test_schema import policy, rule, valid  # the helpers used by the schema tests
    with pytest.raises(ValidationError, match="must start with /"):
        valid(policy(rule(when=[{"type": "request_matches", "method": "*", "path": "*bank*"}])))


# --- normalisation -------------------------------------------------------------------------------


@pytest.mark.parametrize("raw, segments", [
    ("/a/b?x=1#frag", ["a", "b"]),
    ("//a///b/", ["a", "b"]),
    ("/%5F%5Fadmin/reset", ["__admin", "reset"]),
    ("/A/B", ["a", "b"]),
    ("/%252e%252e/x", ["%2e%2e", "x"]),          # decoded exactly once: the literal text %2e, not a dot
    ("/a%3Fb", ["a?b"]),                          # an encoded ? is part of the path, not a query
    ("/", []),
])
def test_normalisation(raw, segments):
    assert normalise_path(raw) == segments


@pytest.mark.parametrize("raw", [
    "/a/./b", "/a/../b", "/..", "/a/%2e%2e/b", "/a%2F..%2Fb", "/a\\b", "/a%00b", "/a%0Ab", "/%ff",
    "a/b", "", "http://host/a",
])
def test_a_path_that_cannot_be_normalised_is_rejected(raw):
    with pytest.raises(InvalidPath):
        normalise_path(raw)


def test_an_invalid_path_matches_every_glob_so_a_rule_can_only_over_catch_it():
    assert path_matches("/__admin/**", "/api/../__admin/reset") is True
    assert path_matches("/never/**", "/a/./b") is True


# --- the shipped rules ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [
    "/__admin/reset", "/__admin/state_hash", "/__admin/diff?since=x", "/__admin", "/__admin/",
    "//__admin/reset", "/api/../__admin/reset", "/%5F%5Fadmin/reset", "/__ADMIN/reset", "/__admin/reset?x=1",
    "/__admin/a/b/c", "/./__admin/reset", "/%2e%2e/__admin/reset",
])
def test_org_004_catches_every_spelling_of_an_admin_path(raw):
    assert rule_matches("ORG-004", raw), raw


@pytest.mark.parametrize("raw", ["/x/__admin/reset", "/__administrator", "/api/__admin", "/admin/reset", "/"])
def test_org_004_does_not_catch_near_misses(raw):
    assert not rule_matches("ORG-004", raw), raw


@pytest.mark.parametrize("rule_id", ["ORG-001", "ORG-003"])
@pytest.mark.parametrize("raw, caught", [
    ("/approvals/1/decide", True), ("/api/approvals/1/decide", True), ("/API/Approvals/1/Decide?x=1", True),
    ("/api/approvals/1/x/decide", False), ("/x/approvals/1/decide", False), ("/api/approvals/1", False),
    ("/api/approvals/1/decided", False), ("/approvals/1/decide/more", False),
])
def test_approval_decision_rules_match_only_the_real_decision_routes(rule_id, raw, caught):
    assert rule_matches(rule_id, raw) is caught


@pytest.mark.parametrize("raw, caught", [
    ("/api/vendors/4/bank", True), ("/vendors/4/update-bank", True), ("/api/vendors/4/BANK-details", True),
    ("/api/payments", False), ("/api/vendors/4", False),
])
def test_org_006_catches_any_path_with_a_bank_segment(raw, caught):
    assert rule_matches("ORG-006", raw) is caught
