import asyncio
import xmlrpc.client
from types import SimpleNamespace

import pytest
from conftest import build_tools
from mcp.server.fastmcp import FastMCP

from mcpserver.config import OdooConfig
from mcpserver.tools import OdooTools

WRITE_TOOLS = {"create_order", "create_customer"}


def list_tools(mcp):
    return {t.name: t for t in asyncio.run(mcp.list_tools())}


@pytest.mark.parametrize("raw, count", [("true", 5), ("yes", 5), ("false", 7), ("0", 7), ("", 7)])
def test_read_only_registration(monkeypatch, raw, count):
    monkeypatch.setenv("ODOO_READ_ONLY", raw)
    mcp, _, _ = build_tools()
    registered = list_tools(mcp)
    assert len(registered) == count
    assert (WRITE_TOOLS <= set(registered)) == (count == 7)


def test_annotations():
    mcp, _, _ = build_tools()
    for name, tool in list_tools(mcp).items():
        a = tool.annotations
        assert a is not None, name
        write = name in WRITE_TOOLS
        assert a.readOnlyHint == (not write), name
        assert a.idempotentHint == (not write), name
        assert a.destructiveHint == (name == "create_order"), name


# --- _execute_odoo / error results ---

def test_execute_odoo_reraises_fault_and_passes_args():
    calls = []

    def execute_kw(*a):
        calls.append(a)
        raise xmlrpc.client.Fault(1, "boom")

    cfg = SimpleNamespace(odoo_database="d", auth_credential="k", odoo_read_only=True)
    server = SimpleNamespace(uid=9, models=SimpleNamespace(execute_kw=execute_kw))
    t = OdooTools(FastMCP("t"), cfg, server)
    with pytest.raises(xmlrpc.client.Fault):
        t._execute_odoo("res.partner", "search", [[]], limit=1)
    assert calls == [("d", 9, "k", "res.partner", "search", [[]], {"limit": 1})]


@pytest.mark.parametrize(
    "name, args",
    [
        ("get_customers", {}),
        ("get_products", {}),
        ("search_customers", {"query": "a"}),
        ("create_customer", {"name": "Z"}),
        ("create_order", {"customer_name": "a", "product_id": 1}),
    ],
)
def test_dict_tools_return_error_result_on_fault(name, args):
    result = _failing_tools()[name](**args)
    assert isinstance(result, dict) and result["success"] is False


@pytest.mark.parametrize(
    "name, args",
    [("get_product_details", {"product_name": "a"}), ("get_order_details", {})],
)
def test_string_tools_return_error_string_on_fault(name, args):
    result = _failing_tools()[name](**args)
    assert isinstance(result, str) and result.startswith("Error")


def _failing_tools():
    class AlwaysFail:
        def execute_kw(self, *a):
            raise xmlrpc.client.Fault(1, "boom")

    mcp = FastMCP("t")
    OdooTools(mcp, OdooConfig(), SimpleNamespace(uid=1, models=AlwaysFail()))
    return {t.name: t.fn for t in mcp._tool_manager.list_tools()}


# --- read tools ---

def test_get_customers_domain_shape():
    _, models, fns = build_tools()
    fns["get_customers"]()
    expected = ["|", ("is_company", "=", True), ("parent_id", "=", False)]
    assert models.calls[0][1:3] == ("search_count", [expected])
    assert models.calls[1][1] == "search_read"
    assert models.calls[1][2] == [expected]


def test_get_products_empty_is_dict():
    _, models, fns = build_tools()
    models.execute_kw = lambda *a: []
    assert fns["get_products"]() == {"products": [], "message": "No products available."}


def test_get_products_limit_and_lang():
    _, models, fns = build_tools()
    assert fns["get_products"]("fr", 3) == {"products": [{"id": 5, "name": "P"}]}
    kw = models.calls[0][3]
    assert kw["limit"] == 3 and kw["context"] == {"lang": "fr_FR"}


def test_format_datetime():
    t = OdooTools.__new__(OdooTools)
    t.config = SimpleNamespace(odoo_timezone="Asia/Riyadh")
    assert t._format_datetime("2024-01-01 00:00:00") == "2024-01-01 03:00:00"
    assert t._format_datetime(False) == "N/A"
    assert t._format_datetime(None) == "N/A"


def test_get_order_details_missing_date():
    _, models, fns = build_tools()
    orig = models.execute_kw

    def execute_kw(db, uid, cred, model, method, args, kw):
        if (model, method) == ("sale.order", "search_read"):
            return [{"name": "S1", "date_order": False, "state": "sale", "order_line": [],
                     "amount_total": 1.0, "currency_id": [1, "USD"]}]
        return orig(db, uid, cred, model, method, args, kw)

    models.execute_kw = execute_kw
    out = fns["get_order_details"](fields=["name", "date_order"])
    assert "Order ID: S1" in out and "Date: N/A" in out


# --- ilike escaping ---

def test_escape_like():
    assert OdooTools._escape_like("a%b_c\\") == "a\\%b\\_c\\\\"


def test_search_customers_escapes_query():
    _, models, fns = build_tools()
    fns["search_customers"]("50%_off")
    assert models.calls[0][2] == [[["name", "ilike", "50\\%\\_off"]]]


def test_find_partner_escapes_name():
    _, models, fns = build_tools()
    fns["create_customer"]("a%b")
    assert models.calls[0][2] == [[["name", "=ilike", "a\\%b"]]]


def test_create_customer_country_lookup_is_escaped():
    _, models, fns = build_tools()
    fns["create_customer"]("X", country="F_r")
    assert models.find("res.country", "search_read")[0][2] == [[("name", "ilike", "F\\_r")]]


# --- create_customer ---

def test_create_customer_duplicate_exact_only():
    _, models, fns = build_tools()
    r = fns["create_customer"]("john")
    assert r["success"] is False and r["existing_id"] == 1
    assert not models.find("res.partner", "create")


def test_create_customer_partial_match_is_not_duplicate():
    _, models, fns = build_tools(partners=[{"id": 2, "name": "Johnson"}])
    r = fns["create_customer"]("John")
    assert r["success"] is True and r["customer_id"] == 77


def test_create_customer_requires_name():
    _, _, fns = build_tools()
    assert fns["create_customer"]("  ")["success"] is False


# --- create_order ---

def test_create_order_ambiguous_customer():
    _, models, fns = build_tools()
    r = fns["create_order"]("Ann", 5)
    assert r["success"] is False
    assert r["candidates"] == [{"id": 3, "name": "Ann"}, {"id": 4, "name": "Ann"}]
    assert not models.find("sale.order", "create")


def test_create_order_partial_name_is_not_accepted():
    _, models, fns = build_tools()
    r = fns["create_order"]("Bob", 5)
    assert r["success"] is False
    assert r["candidates"] == [{"id": 5, "name": "Bob Smith"}]
    assert not models.find("sale.order", "create")


def test_create_order_unknown_customer():
    _, models, fns = build_tools()
    r = fns["create_order"]("Nobody", 5)
    assert r["success"] is False and "candidates" not in r
    assert not models.find("sale.order", "create")


def test_create_order_exact_match_case_insensitive():
    _, models, fns = build_tools()
    r = fns["create_order"]("john", 5)
    assert r == {
        "success": True,
        "message": "Order created and confirmed.",
        "order_id": 100,
        "invoice_id": None,
        "total_amount": 10.0,
    }
    assert models.find("sale.order", "create")[0][2][0]["partner_id"] == 1


@pytest.mark.parametrize("qty", [0, -1, float("nan"), float("inf"), "x", True, None])
def test_create_order_rejects_bad_quantity(qty):
    _, models, fns = build_tools()
    r = fns["create_order"]("john", 5, quantity=qty)
    assert r["success"] is False and "Quantity" in r["message"]
    assert not models.find("sale.order", "create")


def test_create_order_requires_product_and_customer():
    _, _, fns = build_tools()
    assert fns["create_order"]("john", 0)["success"] is False
    assert fns["create_order"]("  ", 5)["success"] is False


def test_create_order_id_wrapping_and_full_flow():
    _, models, fns = build_tools()
    r = fns["create_order"]("John", 5, quantity=2.5, finish_payment=True)
    assert r["success"] is True
    assert r["order_id"] == 100 and r["invoice_id"] == 900 and r["total_amount"] == 11.5
    assert "enabled" in r["message"] and "payment registered" in r["message"]
    assert models.find("sale.order.line", "create")[0][2][0]["product_uom_qty"] == 2.5
    # ids are wrapped as a list of ids for method calls
    assert models.find("sale.order", "action_confirm")[0][2] == [[100]]
    assert models.find("account.move", "action_post")[0][2] == [[900]]
    assert models.find("sale.order", "read")[0][2] == [[100], ["invoice_ids"]]
    assert models.find("account.move", "read")[0][2] == [[900], ["amount_total"]]
    wizard = models.find("sale.advance.payment.inv", "create_invoices")[0]
    assert wizard[2] == [[300]] and wizard[3]["context"]["active_ids"] == [100]
    pay = models.find("account.payment.register", "action_create_payments")[0]
    assert pay[2] == [[400]] and pay[3]["context"]["active_ids"] == [900]
    reg = models.find("account.payment.register", "create")[0]
    assert reg[2] == [{"journal_id": 7, "payment_method_line_id": 3}]


def test_create_order_partial_failure_reports_created_records():
    _, models, fns = build_tools(fail=("account.move", "action_post"))
    r = fns["create_order"]("John", 5, create_invoice=True)
    assert r["success"] is False
    assert r["step"] == "post invoice"
    assert r["order_id"] == 100 and r["invoice_id"] == 900
    assert "Do NOT retry" in r["message"]


def test_create_order_failure_before_creation_has_no_ids():
    _, _, fns = build_tools(fail=("sale.order", "create"))
    r = fns["create_order"]("John", 5)
    assert r["success"] is False and r["step"] == "create order"
    assert "order_id" not in r


def test_create_order_missing_journal_creates_nothing():
    _, models, fns = build_tools(journals=[])
    r = fns["create_order"]("John", 5, finish_payment=True)
    assert r["success"] is False and "journal" in r["message"]
    assert not models.find("sale.order", "create")


def test_create_order_configured_journal_not_found(monkeypatch):
    monkeypatch.setenv("ODOO_PAYMENT_JOURNAL", "NOPE")
    _, models, fns = build_tools(journals=[])
    r = fns["create_order"]("John", 5, finish_payment=True)
    assert r["success"] is False and "NOPE" in r["message"]
    domain = models.find("account.journal", "search_read")[0][2][0]
    assert domain[-3:] == ["|", ["name", "=ilike", "NOPE"], ["code", "=ilike", "NOPE"]]
