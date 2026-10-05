import pytest

from acme.db import connect
from acme.seed import reset


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "acme.db")
    reset(connection, "base")
    yield connection
    connection.close()


@pytest.fixture
def make_conn(tmp_path):
    """Connection reset to a chosen seed: make_conn("t9")."""
    opened = []

    def _make(seed: str = "base", now: str | None = None):
        connection = connect(tmp_path / f"acme-{len(opened)}.db")
        reset(connection, seed, *([now] if now else []))
        opened.append(connection)
        return connection

    yield _make
    for connection in opened:
        connection.close()
