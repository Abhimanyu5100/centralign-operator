"""Path globs for `request_matches` rules (D-088, N.83, N.101).

A glob is a list of segments split on `/`. `*` matches inside one segment and never crosses a `/`; `**` is a
whole segment that matches zero or more segments. No other character is a wildcard.

A request path is normalised first (`normalise_path`): query and fragment stripped, percent-decoded exactly
once, repeated slashes collapsed. A path that cannot be normalised safely (a `.` or `..` segment, a backslash,
a control character, bad UTF-8, no leading `/`) raises `InvalidPath`. `path_matches` treats such a path as a
match for EVERY glob, so a rule can only over-catch it, never miss it (fail closed). Matching ignores case:
every rule can only deny or hold a call, so over-matching is the safe direction.
"""

import re
from urllib.parse import unquote

_GLOB_CHARS = re.compile(r"[A-Za-z0-9_\-.~*/]+")


class InvalidPath(ValueError):
    """The request path cannot be normalised; a gate must not let it through."""


def check_glob(pattern: str) -> str:
    """Load-time validation of a rule's path glob; returns it unchanged."""
    if not _GLOB_CHARS.fullmatch(pattern) or not pattern.startswith("/"):
        raise ValueError(f"path glob {pattern!r} must start with / and use only letters, digits, _ - . ~ * and /")
    segments = pattern.split("/")[1:]
    if segments and segments[-1] == "":  # a trailing slash is the same pattern as without it
        segments = segments[:-1]
    for segment in segments:
        if segment == "":
            raise ValueError(f"path glob {pattern!r} has an empty segment (//)")
        if segment in (".", ".."):
            raise ValueError(f"path glob {pattern!r} has a {segment!r} segment")
        if "**" in segment and segment != "**":
            raise ValueError(f"path glob {pattern!r}: ** must be a whole segment")
    return pattern


def normalise_path(raw: str) -> list[str]:
    """The segments of a request path, lower-cased, or `InvalidPath`."""
    path = raw.split("#", 1)[0].split("?", 1)[0]
    try:
        path = unquote(path, errors="strict")  # exactly once: %252e stays the literal text %2e
    except UnicodeDecodeError as exc:
        raise InvalidPath(f"bad percent-encoding in {raw!r}") from exc
    if not path.startswith("/"):
        raise InvalidPath(f"{raw!r} is not an absolute path")
    if "\\" in path or any(ord(c) < 0x20 or ord(c) == 0x7F for c in path):
        raise InvalidPath(f"{raw!r} has a backslash or control character")
    segments = [s for s in path.split("/") if s != ""]
    if any(s in (".", "..") for s in segments):
        raise InvalidPath(f"{raw!r} has a . or .. segment")
    return [s.casefold() for s in segments]


def _segment_regex(segment: str) -> re.Pattern[str]:
    return re.compile("[^/]*".join(re.escape(part) for part in segment.split("*")))


def _match(pattern: list[str], path: list[str]) -> bool:
    if not pattern:
        return not path
    head, rest = pattern[0], pattern[1:]
    if head == "**":
        return any(_match(rest, path[i:]) for i in range(len(path) + 1))
    return bool(path) and _segment_regex(head).fullmatch(path[0]) is not None and _match(rest, path[1:])


def path_matches(pattern: str, raw_path: str) -> bool:
    """True when `raw_path` (as sent, query string and all) matches the glob `pattern`."""
    check_glob(pattern)
    try:
        segments = normalise_path(raw_path)
    except InvalidPath:
        return True
    return _match([s for s in pattern.casefold().split("/") if s != ""], segments)
