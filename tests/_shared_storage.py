"""A ``LocalSharedStorage`` per test that can always become its own owner."""

import socket
import uuid


def fresh_local_storage():
    """A ``LocalSharedStorage`` with its own owner election.

    Every default ``LocalSharedStorage`` in a process shares one owner address,
    which belongs to whichever test's app started first; once that test's server
    stops, later tests time out on it. So each gets a random namespace.

    Without ``AF_UNIX`` (Windows), Dash hashes the namespace to a TCP port in
    49152-65535. If something already listens there (a system service, a test
    server, an earlier test's owner), the bind fails, the storage takes itself
    for a client and dies waiting for an owner that never advertises
    (``ConnectionError: shared-storage owner advertisement not found``). Pick a
    namespace whose port binds now.

    Returns:
        A new, unstarted ``LocalSharedStorage``.
    """
    from dash import LocalSharedStorage
    from dash._shared_storage.local import _tcp_port

    while True:
        namespace = uuid.uuid4().hex
        if hasattr(socket, "AF_UNIX") or _port_binds(_tcp_port(namespace)):
            return LocalSharedStorage(namespace=namespace)


def _port_binds(port: int) -> bool:
    """Whether ``port`` binds the way Dash's owner election binds it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True
