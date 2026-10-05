"""The generated PDF files Acme serves (risks N.61, N.67).

Files live in one directory, `acme/data/files/` (override with `ACME_FILES_DIR`). A name is only ever
looked up in the directory listing, never joined onto a path: a name that does not match the strict
pattern, is not a regular file in the listing, or is a symlink gets the same answer as a missing one.
"""

import os
import re
from pathlib import Path

from acme.mail import ATTACHMENT_PATTERN

DEFAULT_DIR = Path(__file__).parent / "data" / "files"
_NAME = re.compile(ATTACHMENT_PATTERN)


def files_dir() -> Path:
    return Path(os.environ.get("ACME_FILES_DIR") or DEFAULT_DIR)


def _listing() -> dict[str, Path]:
    directory = files_dir()
    if not directory.is_dir():
        return {}
    return {p.name: p for p in directory.iterdir()
            if p.suffix == ".pdf" and p.is_file() and not p.is_symlink() and _NAME.fullmatch(p.name)}


def available() -> list[str]:
    return sorted(_listing())


def exists(name: object) -> bool:
    return isinstance(name, str) and _NAME.fullmatch(name) is not None and name in _listing()


def read(name: object) -> bytes | None:
    """The file's bytes, or None for anything that is not a listed regular PDF."""
    if not exists(name):
        return None
    return _listing()[name].read_bytes()
