import pytest
from typing import Any

import dash.testing.application_runners as _runners

import dash_auth_async.backends as backends


def _stop_quart_gracefully(runner) -> bool:
    """Shut down a quart-backend dash test server via its own shutdown event.

    ThreadedRunner.stop() kills server threads with an async SystemExit,
    which abandons hypercorn's connections mid-flight; on Windows the
    proactor loop's close() then waits forever for the orphaned overlapped
    I/O and pytest hangs in teardown (browser stays open). Dash's Quart
    backend has a graceful path - serve(shutdown_trigger=...) awaits
    backend._ws_shutdown_event - but only the main-thread signal handler
    ever sets it. Set it here, thread-safely, on the server's own loop.

    Returns True if the server thread exited; False means fall back to
    the original kill-based stop.
    """
    backend_server = getattr(runner._app, "backend", None)
    event = getattr(backend_server, "_ws_shutdown_event", None)
    if event is None:
        return False
    # The asyncio.Event binds its loop on first await (in shutdown_trigger),
    # so its private _loop is the hypercorn loop in the server thread.
    loop = getattr(event, "_loop", None)
    if loop is None or loop.is_closed():
        return False
    try:
        loop.call_soon_threadsafe(event.set)
    except (RuntimeError, AttributeError):
        return False
    runner.thread.join(timeout=runner.stop_timeout)
    return not runner.thread.is_alive()


_original_stop = _runners.ThreadedRunner.stop


def _stop_with_graceful_quart(self: Any) -> Any:
    if _stop_quart_gracefully(self):
        self._app = None
        self.started = False
        return
    return _original_stop(self)


_runners.ThreadedRunner.stop = _stop_with_graceful_quart  # type: ignore


@pytest.fixture(autouse=True)
def reset_active_backend():
    """Keep the module-level active backend from leaking between tests."""
    yield
    backends._active_backend = None
