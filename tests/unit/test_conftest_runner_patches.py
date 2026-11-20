"""The test-harness patches in ``tests/conftest.py`` behave as intended."""

import ctypes
import socket
import threading
import uuid
from types import SimpleNamespace

import dash
import pytest
from dash.testing.application_runners import KillerThread
from packaging.version import Version


def test_ct001_kill_tolerates_a_thread_that_exits_mid_kill(monkeypatch):
    """RED before fix: ``KillerThread.kill`` lists the live threads, then sends
    each a ``SystemExit``. A thread that finishes in between (a request thread
    closing its connection) makes the call return 0, and Dash raised
    ``ValueError: Invalid thread id`` at teardown -- a flaky error, not a
    leak, since the thread is already gone."""
    runner_thread = KillerThread(target=lambda: None)  # snapshots old threads
    release = threading.Event()
    worker = threading.Thread(target=release.wait, daemon=True)
    worker.start()  # new since the snapshot, so kill() targets it
    # The worker "exits" between kill()'s listing and its SetAsyncExc call.
    monkeypatch.setattr(ctypes.pythonapi, "PyThreadState_SetAsyncExc", lambda *_args: 0)
    try:
        runner_thread.kill()
    finally:
        release.set()
        worker.join()


@pytest.mark.skipif(
    Version(dash.__version__) < Version("4.5.0"), reason="needs dash>=4.5.0"
)
@pytest.mark.skipif(
    hasattr(socket, "AF_UNIX"), reason="owner port collisions are TCP-only"
)
def test_ct002_fresh_storage_avoids_an_occupied_owner_port(monkeypatch):
    """RED before fix: a namespace whose hashed owner port was already listened
    on made the storage wait 5 s for an owner, then fail with
    ``ConnectionError: shared-storage owner advertisement not found``."""
    from dash._shared_storage.local import _tcp_port

    from tests import _shared_storage

    taken, free = uuid.uuid4().hex, uuid.uuid4().hex
    with socket.socket() as squatter:
        squatter.bind(("127.0.0.1", _tcp_port(taken)))
        squatter.listen()
        candidates = iter([SimpleNamespace(hex=taken), SimpleNamespace(hex=free)])
        monkeypatch.setattr(_shared_storage.uuid, "uuid4", lambda: next(candidates))

        storage = _shared_storage.fresh_local_storage()
        try:
            storage.start()
            storage.set("k", "v")
            assert storage.get("k") == "v"
        finally:
            storage.close()
