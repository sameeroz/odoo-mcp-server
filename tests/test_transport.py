import socket
import socketserver
import threading
import time
from xmlrpc.server import SimpleXMLRPCServer

import pytest

from mcpserver.odoo_mcp_server import (
    _make_proxy,
    _TimeoutSafeTransport,
    _TimeoutTransport,
)


class _ThreadedServer(socketserver.ThreadingMixIn, SimpleXMLRPCServer):
    daemon_threads = True


@pytest.fixture
def server():
    srv = _ThreadedServer(("127.0.0.1", 0), logRequests=False)
    srv.register_function(lambda: "pong", "ping")
    srv.register_function(lambda: time.sleep(3) or "slow", "slow")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def test_http_scheme_uses_plain_transport():
    proxy = _make_proxy("http://127.0.0.1:1", 5)
    assert isinstance(proxy._ServerProxy__transport, _TimeoutTransport)


@pytest.mark.parametrize("url", ["https://example.com/x", "HTTPS://example.com/x"])
def test_https_scheme_uses_safe_transport(url):
    proxy = _make_proxy(url, 5)
    assert isinstance(proxy._ServerProxy__transport, _TimeoutSafeTransport)


def test_each_proxy_has_own_transport():
    a = _make_proxy("https://example.com/x", 1)
    b = _make_proxy("https://example.com/x", 1)
    assert a._ServerProxy__transport is not b._ServerProxy__transport


def test_call_succeeds(server):
    assert _make_proxy(f"http://127.0.0.1:{server}", 5).ping() == "pong"


def test_timeout_is_applied(server):
    proxy = _make_proxy(f"http://127.0.0.1:{server}", 0.5)
    start = time.monotonic()
    with pytest.raises((TimeoutError, socket.timeout)):
        proxy.slow()
    assert time.monotonic() - start < 2.5
