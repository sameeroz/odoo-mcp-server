import asyncio
import xmlrpc.client
from types import SimpleNamespace

import pytest
from conftest import build_tools
from mcp.server.fastmcp import FastMCP

from mcpserver.config import OdooConfig
from mcpserver.tools import (
    DEFAULT_PRODUCT_LIMIT,
    MAX_LIMIT,
    MAX_PRODUCT_LIMIT,
    ORDER_DISPLAY_FIELDS,
    OdooTools,
    safe_error,
)

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
    models.execute_kw = lambda *a: 0 if a[4] == "search_count" else []
    assert fns["get_products"]() == {
        "products": [], "total_count": 0, "returned": 0, "offset": 0,
        "message": "No products available.",
    }


def test_get_products_limit_and_lang():
    _, models, fns = build_tools()
    assert fns["get_products"]("fr", 3, 2) == {
        "products": [{"id": 5, "name": "P"}], "total_count": 123, "returned": 1, "offset": 2,
    }
    kw = models.find("product.product", "search_read")[0][3]
    assert kw["limit"] == 3 and kw["offset"] == 2 and kw["context"] == {"lang": "fr_FR"}


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


# --- get_products paging ---

def test_get_products_default_limit_and_cap():
    _, models, fns = build_tools()
    fns["get_products"]()
    fns["get_products"](limits=10_000)
    reads = models.find("product.product", "search_read")
    assert reads[0][3]["limit"] == DEFAULT_PRODUCT_LIMIT == 50
    assert reads[0][3]["offset"] == 0
    assert reads[1][3]["limit"] == MAX_PRODUCT_LIMIT == 500


# --- get_order_details batching ---

ORDERS = [
    {"id": 1, "name": "S1", "date_order": "2024-01-01 00:00:00", "state": "sale",
     "order_line": [11, 12], "amount_total": 30.0, "currency_id": [1, "USD"]},
    {"id": 2, "name": "S2", "date_order": False, "state": "draft",
     "order_line": [13], "amount_total": 5.0, "currency_id": [1, "USD"]},
    {"id": 3, "name": "S3", "date_order": "2024-01-02 10:00:00", "state": "draft",
     "order_line": [], "amount_total": 0.0, "currency_id": [1, "USD"]},
]
LINES = [
    {"id": 13, "product_id": [9, "Widget"], "product_uom_qty": 1.0, "price_unit": 5.0},
    {"id": 12, "product_id": [8, "Gadget"], "product_uom_qty": 2.0, "price_unit": 10.0},
    {"id": 11, "product_id": [7, "Thing"], "product_uom_qty": 1.0, "price_unit": 10.0},
]
EXPECTED_ORDERS = """Order ID: S1
Date: 2024-01-01 00:00:00
State: sale
Order Items:
- Thing, Qty: 1.0, Price: 10.0 each
- Gadget, Qty: 2.0, Price: 10.0 each
Total Amount: 30.0 USD

Order ID: S2
Date: N/A
State: draft
Order Items:
- Widget, Qty: 1.0, Price: 5.0 each
Total Amount: 5.0 USD

Order ID: S3
Date: 2024-01-02 10:00:00
State: draft
Order Items:
- No order items found for []
Total Amount: 0.0 USD"""


def _orders_tools():
    _, models, fns = build_tools()
    orig = models.execute_kw

    def execute_kw(db, uid, cred, model, method, args, kw):
        if (model, method) == ("sale.order", "search_read"):
            models.calls.append((model, method, args, kw))
            return ORDERS
        if (model, method) == ("sale.order.line", "read"):
            models.calls.append((model, method, args, kw))
            return LINES  # deliberately not in id order
        return orig(db, uid, cred, model, method, args, kw)

    models.execute_kw = execute_kw
    return models, fns


def test_get_order_details_batches_line_read_and_keeps_format():
    models, fns = _orders_tools()
    assert fns["get_order_details"](limits=3) == EXPECTED_ORDERS
    assert len(models.calls) == 2
    assert len(models.find("sale.order.line", "read")) == 1
    assert models.find("sale.order.line", "read")[0][2] == [[11, 12, 13]]
    kw = models.find("sale.order", "search_read")[0][3]
    assert set(kw["fields"]) == set(ORDER_DISPLAY_FIELDS) and kw["limit"] == 3


def test_get_order_details_skips_line_read_when_not_displayed():
    models, fns = _orders_tools()
    out = fns["get_order_details"](limits=3, fields=["name", "state"])
    assert out.startswith("Order ID: S1\nState: sale\n\nOrder ID: S2")
    assert not models.find("sale.order.line", "read")


# --- validation ---

@pytest.mark.parametrize(
    "name, args",
    [
        ("get_products", {"limits": 0}),
        ("get_products", {"limits": True}),
        ("get_products", {"offset": -1}),
        ("get_products", {"offset": "1"}),
        ("get_customers", {"limit": 0}),
        ("get_customers", {"limit": 1.5}),
        ("get_customers", {"limit": True}),
        ("get_customers", {"offset": -1}),
        ("search_customers", {"query": "a", "limit": -3}),
        ("search_customers", {"query": "a", "limit": "5"}),
    ],
)
def test_dict_tools_reject_bad_paging(name, args):
    _, models, fns = build_tools()
    r = fns[name](**args)
    assert r["success"] is False and "must be" in r["message"]
    assert not models.calls


@pytest.mark.parametrize(
    "args",
    [
        {"limits": 0},
        {"limits": True},
        {"limits": "2"},
        {"order_ids": [1, "2"]},
        {"order_ids": [True]},
        {"order_ids": "1"},
        {"fields": ["name", "secret"]},
        {"fields": "name"},
    ],
)
def test_get_order_details_rejects_bad_input(args):
    _, models, fns = build_tools()
    r = fns["get_order_details"](**args)
    assert isinstance(r, str) and r.startswith("Error")
    assert not models.calls


def test_get_order_details_unknown_field_lists_allowed():
    _, _, fns = build_tools()
    r = fns["get_order_details"](fields=["secret"])
    assert "secret" in r and all(f in r for f in ORDER_DISPLAY_FIELDS)


def test_limits_are_clamped_to_max():
    _, models, fns = build_tools()
    fns["get_customers"](limit=10_000)
    fns["search_customers"]("a", limit=10_000)
    fns["get_order_details"](limits=10_000)
    assert models.find("res.partner", "search_read")[0][3]["limit"] == MAX_LIMIT == 200
    assert models.find("res.partner", "search_read")[1][3]["limit"] == MAX_LIMIT
    assert models.find("sale.order", "search_read")[0][3]["limit"] == MAX_LIMIT


def test_order_ids_domain_and_valid_ints():
    _, models, fns = build_tools()
    fns["get_order_details"](order_ids=[4, 5])
    assert models.find("sale.order", "search_read")[0][2] == [[["id", "in", [4, 5]]]]


def test_search_by_invalid_lists_options():
    _, models, fns = build_tools()
    r = fns["search_customers"]("a", search_by="nmae")
    assert r["success"] is False
    assert all(o in r["message"] for o in ("name", "email", "phone", "all"))
    assert not models.calls


def test_search_by_case_insensitive():
    _, models, fns = build_tools()
    fns["search_customers"]("a", search_by="EMAIL")
    assert models.calls[0][2] == [[["email", "ilike", "a"]]]


# --- error sanitizing ---

TRACEBACK_FAULT = (
    "Traceback (most recent call last):\n"
    '  File "/opt/odoo/odoo/http.py", line 1, in dispatch\n'
    "    result = secret_internal_call(db_password)\n"
    '  File "/opt/odoo/addons/sale/models/sale.py", line 2, in create\n'
    "odoo.exceptions.AccessError: You are not allowed to access 'Sales Order' records."
)


def test_safe_error_strips_traceback():
    msg = safe_error(xmlrpc.client.Fault(1, TRACEBACK_FAULT))
    assert msg == "Odoo error: odoo.exceptions.AccessError: You are not allowed to access 'Sales Order' records."
    assert "File" not in msg and "secret_internal_call" not in msg


def test_safe_error_first_line_truncated_and_readable():
    assert safe_error(xmlrpc.client.Fault(1, "Access Denied\nsecond")) == "Odoo error: Access Denied"
    long = safe_error(xmlrpc.client.Fault(1, "x" * 1000))
    assert len(long) == len("Odoo error: ") + 200
    assert safe_error(xmlrpc.client.Fault(1, "")) == "Odoo error: request failed"


def test_safe_error_generic_for_other_exceptions():
    assert safe_error(ConnectionRefusedError("10.0.0.5:8069 secret")) == (
        "Odoo request failed: ConnectionRefusedError"
    )


def test_tool_error_results_do_not_leak_detail():
    class Boom:
        def __init__(self, exc):
            self.exc = exc

        def execute_kw(self, *a):
            raise self.exc

    for exc in (xmlrpc.client.Fault(1, TRACEBACK_FAULT), OSError("db_password=hunter2")):
        mcp = FastMCP("t")
        OdooTools(mcp, OdooConfig(), SimpleNamespace(uid=1, models=Boom(exc)))
        fns = {t.name: t.fn for t in mcp._tool_manager.list_tools()}
        results = [
            fns["get_products"]()["message"],
            fns["get_customers"]()["message"],
            fns["search_customers"]("a")["message"],
            fns["create_customer"]("Z")["message"],
            fns["create_order"]("a", 1)["message"],
            fns["get_product_details"]("a"),
            fns["get_order_details"](),
        ]
        for text in results:
            assert "Traceback" not in text and "File " not in text
            assert "secret_internal_call" not in text and "hunter2" not in text


def test_create_order_one_invoice_failure_keeps_message():
    _, models, fns = build_tools()
    orig = models.execute_kw

    def execute_kw(db, uid, cred, model, method, args, kw):
        if (model, method) == ("sale.order", "read") and args[1] == ["invoice_ids"]:
            return [{"invoice_ids": [1, 2]}]
        return orig(db, uid, cred, model, method, args, kw)

    models.execute_kw = execute_kw
    r = fns["create_order"]("John", 5, create_invoice=True)
    assert r["success"] is False and r["step"] == "create invoice" and r["order_id"] == 100
    assert "Expected exactly one invoice on order 100, found [1, 2]" in r["message"]


def test_create_order_fault_with_traceback_still_sanitized():
    _, models, fns = build_tools()
    orig = models.execute_kw

    def execute_kw(db, uid, cred, model, method, args, kw):
        if (model, method) == ("sale.order", "action_confirm"):
            raise xmlrpc.client.Fault(1, TRACEBACK_FAULT)
        return orig(db, uid, cred, model, method, args, kw)

    models.execute_kw = execute_kw
    r = fns["create_order"]("John", 5)
    assert r["order_id"] == 100 and "AccessError" in r["message"]
    assert "Traceback" not in r["message"] and "secret_internal_call" not in r["message"]
