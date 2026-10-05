import pytest
from mcp import MCPError

from mcpserver import __main__ as entry


def test_config_error_exits_1(monkeypatch, capsys):
    monkeypatch.delenv("ODOO_URL")
    assert entry.main() == 1
    assert "Configuration validation error" in capsys.readouterr().err


def test_empty_env_exits_1(monkeypatch):
    for var in ("ODOO_URL", "ODOO_DATABASE", "ODOO_API_KEY", "ODOO_USERNAME"):
        monkeypatch.delenv(var)
    assert entry.main() == 1


class _Server:
    exc = None

    def __init__(self, mcp, config):
        pass

    def initialize_server(self):
        if self.exc:
            raise self.exc


@pytest.mark.parametrize(
    "exc, code",
    [
        (None, 0),
        (KeyboardInterrupt(), 0),
        (MCPError(1, "x"), 1),
        (ValueError("bad"), 1),
        (RuntimeError("boom"), 1),
    ],
)
def test_exit_codes(monkeypatch, exc, code):
    server = type("S", (_Server,), {"exc": exc})
    monkeypatch.setattr(entry, "OdooMCPServer", server)
    monkeypatch.setattr(entry.mcp, "run", lambda: None)
    assert entry.main() == code
