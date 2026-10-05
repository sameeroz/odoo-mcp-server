import xmlrpc.client
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP

from mcpserver.config import OdooConfig
from mcpserver.tools import OdooTools

PARTNERS = [
    {"id": 1, "name": "John"},
    {"id": 2, "name": "Johnson"},
    {"id": 3, "name": "Ann"},
    {"id": 4, "name": "Ann"},
    {"id": 5, "name": "Bob Smith"},
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Start every test without ODOO_* variables, with a valid API-key setup."""
    import os

    for key in list(os.environ):
        if key.startswith("ODOO_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("ODOO_URL", "http://odoo.test")
    monkeypatch.setenv("ODOO_DATABASE", "db")
    monkeypatch.setenv("ODOO_API_KEY", "key")
    monkeypatch.setenv("ODOO_USERNAME", "user")


class FakeModels:
    """Stub for the XML-RPC object proxy; records calls, emulates the models used."""

    def __init__(self, partners=None, fail=None, journals=None):
        self.calls = []
        self.partners = PARTNERS if partners is None else partners
        self.fail = fail
        self.journals = (
            [{"id": 7, "name": "Bank", "inbound_payment_method_line_ids": [3]}]
            if journals is None
            else journals
        )

    def execute_kw(self, db, uid, cred, model, method, args, kw):
        self.calls.append((model, method, args, kw))
        if self.fail == (model, method):
            raise xmlrpc.client.Fault(1, "boom")
        if (model, method) == ("product.product", "search_count"):
            return 123
        if model == "product.product":
            return [{"id": 5, "name": "P"}]
        if (model, method) == ("res.partner", "create"):
            return 77
        if (model, method) == ("res.partner", "search_count"):
            return len(self.partners)
        if model == "res.partner":
            _, op, value = args[0][0]
            if op == "=ilike":
                return [p for p in self.partners if p["name"].lower() == value.lower()]
            return [p for p in self.partners if value.lower() in p["name"].lower()]
        if model == "account.journal":
            return self.journals
        results = {
            ("sale.order", "create"): 100,
            ("sale.order", "search_read"): [],
            ("sale.order.line", "read"): [],
            ("sale.order.line", "create"): 200,
            ("sale.advance.payment.inv", "create"): 300,
            ("sale.order", "read"): [{"invoice_ids": [900], "amount_total": 10.0}],
            ("account.move", "read"): [{"amount_total": 11.5}],
            ("account.payment.register", "create"): 400,
        }
        return results.get((model, method), True)

    def find(self, model, method):
        return [c for c in self.calls if c[:2] == (model, method)]


def build_tools(**kwargs):
    """Register OdooTools on a fresh FastMCP; returns (mcp, models, tools-by-name)."""
    models = FakeModels(**kwargs)
    server = SimpleNamespace(uid=2, models=models)
    mcp = FastMCP("test")
    OdooTools(mcp, OdooConfig(), server)
    tools = {t.name: t.fn for t in mcp._tool_manager.list_tools()}
    return mcp, models, tools
