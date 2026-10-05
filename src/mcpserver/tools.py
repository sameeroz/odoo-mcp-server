from typing import Any, List
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from datetime import datetime, timezone
import logging
import math
import xmlrpc.client
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class OdooTools:

    def __init__(self, mcp: FastMCP, config, odoo_server):
        self.mcp = mcp
        self.config = config
        self.odoo_server = odoo_server
        self._add_read_tools()
        if config.odoo_read_only:
            logger.info("ODOO_READ_ONLY is set: write tools (create_customer, create_order) not registered.")
        else:
            self._add_write_tools()

    def _execute_odoo(self, model: str, method: str, args, **kwargs) -> Any:
        """Helper to execute Odoo XML-RPC calls. Logs and re-raises any failure
        (xmlrpc.client.Fault is preserved so callers can tell Odoo errors apart)."""
        try:
            return self.odoo_server.models.execute_kw(
                self.config.odoo_database,
                self.odoo_server.uid,
                self.config.auth_credential,
                model,
                method,
                args,
                kwargs,
            )
        except Exception as e:
            logger.error("Odoo call failed for %s.%s: %s", model, method, e)
            raise

    def _format_datetime(self, utc_string) -> str:
        """Convert UTC time string from Odoo to configured local time."""
        if not utc_string:  # Odoo returns False for empty fields
            return "N/A"
        utc_time = datetime.strptime(utc_string, "%Y-%m-%d %H:%M:%S")
        local_tz = ZoneInfo(self.config.odoo_timezone)
        return (
            utc_time.replace(tzinfo=timezone.utc)
            .astimezone(local_tz)
            .strftime("%Y-%m-%d %H:%M:%S")
        )

    def _get_order_lines(self, order_line_ids: List[int]) -> str:
        """Retrieve and format order line details."""

        order_lines = self._execute_odoo(
            "sale.order.line",
            "read",
            [order_line_ids],
            **{
                "fields": [
                    "product_id",
                    "name",
                    "price_unit",
                    "product_uom_qty",
                    "price_subtotal",
                ],
                "context": {"lang": "en_US"},
            },
        )

        if not order_lines:
            return f"- No order items found for {order_line_ids}"

        lines_text = []
        for item in order_lines:
            lines_text.append(
                f"- {item['product_id'][1]}, Qty: {item['product_uom_qty']}, "
                f"Price: {item['price_unit']} each"
            )
        return "\n".join(lines_text)

    @staticmethod
    def _escape_like(value: str) -> str:
        """Escape LIKE wildcards so user text is matched literally in (=)ilike searches."""
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _find_partners_by_name(self, name: str, limit: int = 5):
        """
        Look up partners by name, exact (case-insensitive) matches first.
        Returns (exact, fuzzy): lists of {id, name}. `fuzzy` is only populated
        when there is no exact match.
        """
        escaped = self._escape_like(name.strip())
        search = dict(fields=["id", "name"], limit=limit, order="id asc")
        exact = self._execute_odoo(
            "res.partner", "search_read", [[["name", "=ilike", escaped]]], **search
        )
        if exact:
            return exact, []
        fuzzy = self._execute_odoo(
            "res.partner", "search_read", [[["name", "ilike", escaped]]], **search
        )
        return [], fuzzy

    def _get_partner_id_by_name(self, name):
        """
        Fetches the partner ID from Odoo given a contact (customer) name.
        Only an exact (case-insensitive) name match counts; fuzzy matches are ignored.
        Returns the partner ID if found, otherwise None.
        """
        exact, _ = self._find_partners_by_name(name, limit=1)
        return exact[0]["id"] if exact else None

    def _get_payment_journal(self):
        """
        Returns (journal_id, payment_method_line_id, error). If ODOO_PAYMENT_JOURNAL is set
        it is matched (exactly, case-insensitive) against journal name or code; otherwise the
        first bank/cash journal with an inbound payment method line is used.
        """
        domain = [["type", "in", ["bank", "cash"]]]
        configured = self.config.odoo_payment_journal
        if configured:
            escaped = self._escape_like(configured)
            domain += ["|", ["name", "=ilike", escaped], ["code", "=ilike", escaped]]
        journals = self._execute_odoo(
            "account.journal",
            "search_read",
            [domain],
            **{"fields": ["id", "name", "inbound_payment_method_line_ids"], "order": "sequence, id"},
        )
        for journal in journals:
            if journal["inbound_payment_method_line_ids"]:
                return journal["id"], journal["inbound_payment_method_line_ids"][0], None
        if configured:
            return None, None, (
                f"Payment journal '{configured}' (ODOO_PAYMENT_JOURNAL) was not found as a "
                "bank/cash journal with an inbound payment method."
            )
        return None, None, (
            "No bank or cash journal with an inbound payment method was found. "
            "Configure one in Odoo or set ODOO_PAYMENT_JOURNAL."
        )

    def _add_read_tools(self):
        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=True, destructiveHint=False, idempotentHint=True
            )
        )
        def get_products(product_names_lang: str = "en", limits: int | None = None) -> dict:
            """
            Returns a list of products from Odoo.
            Args:
                product_names_lang: the language to use for the product names.
                limits: the number of products to return, if None, all products are returned.

            Returns:
                A dictionary with a list of products, each product is a dictionary with 'name' and 'list_price' keys.
            """

            supported_languages = {
                "en": "en_US",
                "ar": "ar_001",
                "fr": "fr_FR",
                "es": "es_ES",
            }

            if product_names_lang:
                lang_key = product_names_lang.strip().lower()
                product_names_lang = supported_languages.get(lang_key, "en_US")
            else:
                product_names_lang = "en_US"

            try:
                products = self._execute_odoo(
                    "product.product",
                    "search_read",
                    [[]],
                    **{
                        "fields": ["name", "list_price"],
                        "context": {"lang": product_names_lang},
                        **({"limit": limits} if limits else {}),
                    },
                )
            except Exception as e:
                return {"success": False, "message": f"Failed to retrieve products: {e}"}

            if not products:
                return {"products": [], "message": "No products available."}

            return {"products": products}

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=True, destructiveHint=False, idempotentHint=True
            )
        )
        def get_product_details(product_name: str):
            """
            Get product details from Odoo by product name.

            Args:
                product_name: the name of the product to search for.

            Returns:
                A string with product details.
            """

            if not product_name:
                return "Product name is required."

            language_fallbacks = ["en_US", "ar_001"]
            product_data = None

            try:
                for lang in language_fallbacks:

                    searched_products = self._execute_odoo(
                        "product.product",
                        "search_read",
                        [[["name", "ilike", self._escape_like(product_name)]]],
                        **{
                            "fields": ["id", "name", "list_price", "description_sale"],
                            "limit": 1,
                            "context": {"lang": (lang)},
                        },
                    )

                    if searched_products:
                        product_data = searched_products[0]
                        break
            except Exception as e:
                return f"Error: failed to retrieve product details: {e}"

            if not product_data:
                return f"No product found with the name: {product_name}"

            return (
                f"Product Name: {product_data['name']}\n"
                f"Price: ${product_data['list_price']}\n"
                f"Description: {product_data.get('description_sale', 'No description available.')}"
            )

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=True, destructiveHint=False, idempotentHint=True
            )
        )
        def get_order_details(
            limits: int = 1, order_ids: List[Any] = None, fields: List[str] = None
        ):
            """
            Retrieve and format order details from Odoo.

            Args:
                limits (int): Maximum number of orders to retrieve if order_ids not provided.
                order_ids (List[int], optional): Specific order IDs to fetch.
                fields (List[str], optional): Specific fields to include in the output.
                                            If None, full order details are returned.

            Returns:
                str: Human-readable formatted order details.
            """

            search_domain = [] if order_ids is None else [["id", "in", order_ids]]

            try:
                orders = self._execute_odoo(
                    "sale.order",
                    "search_read",
                    [
                        [
                            # ["partner_id.id", "=", emails[user_email]] # Filter by Employee Id
                            *search_domain
                        ]
                    ],
                    **{"limit": limits},
                )
            except Exception as e:
                return f"Error: failed to retrieve orders: {e}"

            if not orders:
                return "No orders available."

            results = []
            for order in orders:
                formatted_order = []

                # Common values
                formatted_date = self._format_datetime(order["date_order"])
                try:
                    order_items = self._get_order_lines(order.get("order_line", []))
                except Exception as e:
                    return f"Error: failed to retrieve order lines: {e}"

                # Determine which fields to display
                display_fields = fields or [
                    "name",
                    "date_order",
                    "state",
                    "order_line",
                    "amount_total",
                    "currency_id",
                ]

                for field in display_fields:
                    match field:
                        case "name":
                            formatted_order.append(f"Order ID: {order['name']}")
                        case "date_order":
                            formatted_order.append(f"Date: {formatted_date}")
                        case "state":
                            formatted_order.append(f"State: {order['state']}")
                        case "order_line":
                            formatted_order.append(f"Order Items:\n{order_items}")
                        case "amount_total":
                            formatted_order.append(
                                f"Total Amount: {order['amount_total']} {order['currency_id'][1]}"
                            )
                        case "currency_id":
                            if "amount_total" not in display_fields:
                                formatted_order.append(
                                    f"Currency: {order['currency_id'][1]}"
                                )

                results.append("\n".join(formatted_order))

            return "\n\n".join(results)

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=True, destructiveHint=False, idempotentHint=True
            )
        )
        def get_customers(limit: int = 20, offset: int = 0) -> dict:
            """
            Retrieve a list of customers (partners) from Odoo.

            Args:
                limit: Maximum number of customers to return (default 20).
                offset: Number of records to skip for pagination (default 0).

            Returns:
                A dictionary with a list of customers and total count.
            """
            domain = ["|", ("is_company", "=", True), ("parent_id", "=", False)]

            try:
                # Get total count
                total_count = self._execute_odoo(
                    "res.partner", "search_count", [domain]
                )

                customers = self._execute_odoo(
                    "res.partner",
                    "search_read",
                    [domain],
                    **{
                        "fields": [
                            "id", "name", "email", "phone", "mobile",
                            "street", "city", "country_id",
                            "customer_rank", "credit", "debit",
                        ],
                        "limit": limit,
                        "offset": offset,
                        "order": "name asc",
                    },
                )
            except Exception as e:
                return {"success": False, "message": f"Failed to retrieve customers: {e}"}

            if not customers:
                return {"customers": [], "total_count": 0, "message": "No customers found."}

            return {
                "customers": customers,
                "total_count": total_count,
                "returned": len(customers),
                "offset": offset,
            }

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=True, destructiveHint=False, idempotentHint=True
            )
        )
        def search_customers(
            query: str, search_by: str = "name", limit: int = 10
        ) -> dict:
            """
            Search for customers in Odoo by name, email, or phone.

            Args:
                query: The search term to look for.
                search_by: Field to search by - 'name', 'email', 'phone', or 'all' (default 'name').
                limit: Maximum number of results to return (default 10).

            Returns:
                A dictionary with matching customers.
            """
            if not query or not query.strip():
                return {"success": False, "message": "Search query is required."}

            q = self._escape_like(query)
            search_fields = {
                "name": [["name", "ilike", q]],
                "email": [["email", "ilike", q]],
                "phone": ["|", ["phone", "ilike", q], ["mobile", "ilike", q]],
                "all": [
                    "|", "|", "|",
                    ["name", "ilike", q],
                    ["email", "ilike", q],
                    ["phone", "ilike", q],
                    ["mobile", "ilike", q],
                ],
            }

            domain = search_fields.get(search_by.lower(), search_fields["name"])

            try:
                customers = self._execute_odoo(
                    "res.partner",
                    "search_read",
                    [domain],
                    **{
                        "fields": [
                            "id", "name", "email", "phone", "mobile",
                            "street", "city", "country_id",
                        ],
                        "limit": limit,
                    },
                )
            except Exception as e:
                return {"success": False, "message": f"Failed to search customers: {e}"}

            if not customers:
                return {"customers": [], "message": f"No customers found matching '{query}'."}

            return {"customers": customers, "count": len(customers)}

    def _add_write_tools(self):
        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False, destructiveHint=True, idempotentHint=False
            )
        )
        def create_order(
            customer_name: str,
            product_id: int,
            quantity: float = 1,
            create_invoice: bool = False,
            finish_payment: bool = False,
        ) -> dict:
            """
            Create and confirm a sales order in Odoo, optionally invoicing and paying it.
            This confirms the order and, if requested, posts an invoice and registers a
            payment. It is NOT idempotent: do not retry blindly, see the failure result.

            Args:
                customer_name (str): Customer name. Must match exactly one customer
                    (case-insensitive). If there are several or only partial matches,
                    nothing is created and the candidates are returned for the caller
                    to choose from.
                product_id (int): The ID of the product to order.
                quantity (float, optional): Quantity to order, must be greater than 0 (default 1).
                create_invoice (bool, optional): Create and post a customer invoice for the order.
                finish_payment (bool, optional): Register a full payment for the invoice
                    using a bank/cash journal. Implies create_invoice (enabled automatically).

            Returns:
                Dict[str, Any]: success, message, and order_id / invoice_id / total_amount.
                If a step fails after the order was created, success is False and the
                result contains the ids created so far plus the failed 'step'.
            """
            created = {}
            step = "validation"
            try:
                if not product_id:
                    return {
                        "success": False,
                        "message": "Product ID is required to create an order.",
                    }

                if customer_name is None or customer_name.strip() == "":
                    return {
                        "success": False,
                        "message": "Customer name is required to create an order.",
                    }

                if (
                    isinstance(quantity, bool)
                    or not isinstance(quantity, (int, float))
                    or not math.isfinite(quantity)
                    or quantity <= 0
                ):
                    return {
                        "success": False,
                        "message": f"Quantity must be a number greater than 0 - got: {quantity}",
                    }

                notes = []
                if finish_payment and not create_invoice:
                    create_invoice = True
                    notes.append("finish_payment requires an invoice, so create_invoice was enabled.")

                # --- Check product existence ---
                step = "check product"
                check_product_existence = self._execute_odoo(
                    "product.product",
                    "search_read",
                    [[["id", "=", product_id]]],
                    **{
                        "fields": ["id", "name", "list_price", "description_sale"],
                        "limit": 1,
                    },
                )

                if not check_product_existence:
                    return {
                        "success": False,
                        "message": f"No product found with the ID: {product_id}",
                    }

                # --- Resolve customer: exact match only, never guess ---
                step = "resolve customer"
                exact, fuzzy = self._find_partners_by_name(customer_name)
                if len(exact) == 1:
                    partner_id = exact[0]["id"]
                elif exact or fuzzy:
                    candidates = [{"id": p["id"], "name": p["name"]} for p in (exact or fuzzy)][:5]
                    reason = "Multiple customers match" if exact else "No exact customer match for"
                    return {
                        "success": False,
                        "message": (
                            f"{reason} '{customer_name}'. No order was created; "
                            "retry with the exact customer name."
                        ),
                        "candidates": candidates,
                    }
                else:
                    return {
                        "success": False,
                        "message": f"No customer found with the name: {customer_name}",
                    }

                # --- Resolve payment journal up front so we fail before creating anything ---
                journal_id = payment_method_line_id = None
                if finish_payment:
                    step = "resolve payment journal"
                    journal_id, payment_method_line_id, journal_error = self._get_payment_journal()
                    if journal_error:
                        return {"success": False, "message": journal_error}

                # --- Create sales order ---
                step = "create order"
                order_id = self._execute_odoo(
                    "sale.order",
                    "create",
                    [
                        {
                            "partner_id": partner_id,
                            "state": "draft",
                        }
                    ],
                )
                created["order_id"] = order_id
                logger.info("create_order: created sale.order id=%s", order_id)

                # --- Create order line BEFORE confirming ---
                step = "create order line"
                self._execute_odoo(
                    "sale.order.line",
                    "create",
                    [
                        {
                            "order_id": order_id,
                            "product_id": product_id,
                            "product_uom_qty": quantity,
                        }
                    ],
                )

                # --- Confirm order ---
                step = "confirm order"
                self._execute_odoo("sale.order", "action_confirm", [[order_id]])
                logger.info("create_order: confirmed sale.order id=%s", order_id)

                invoice_id = None
                payment_registered = False

                if create_invoice:
                    # --- Create invoice through the public invoicing wizard ---
                    step = "create invoice"
                    wizard_ctx = {
                        "context": {
                            "active_model": "sale.order",
                            "active_ids": [order_id],
                            "active_id": order_id,
                        }
                    }
                    wizard_id = self._execute_odoo(
                        "sale.advance.payment.inv",
                        "create",
                        [{"advance_payment_method": "delivered"}],
                        **wizard_ctx,
                    )
                    self._execute_odoo(
                        "sale.advance.payment.inv", "create_invoices", [[wizard_id]], **wizard_ctx
                    )
                    order_data = self._execute_odoo(
                        "sale.order", "read", [[order_id], ["invoice_ids"]]
                    )
                    invoice_ids = order_data[0].get("invoice_ids", []) if order_data else []
                    if len(invoice_ids) != 1:
                        raise RuntimeError(
                            f"Expected exactly one invoice on order {order_id}, found {invoice_ids}"
                        )
                    invoice_id = invoice_ids[0]
                    created["invoice_id"] = invoice_id
                    logger.info(
                        "create_order: created account.move id=%s for sale.order id=%s",
                        invoice_id, order_id,
                    )

                    # --- Post the invoice ---
                    step = "post invoice"
                    self._execute_odoo("account.move", "action_post", [[invoice_id]])
                    logger.info("create_order: posted account.move id=%s", invoice_id)

                    # --- Register payment ---
                    if finish_payment:
                        step = "register payment"
                        payment_ctx = {
                            "context": {
                                "active_model": "account.move",
                                "active_ids": [invoice_id],
                            }
                        }
                        payment_register_id = self._execute_odoo(
                            "account.payment.register",
                            "create",
                            [
                                {
                                    "journal_id": journal_id,
                                    "payment_method_line_id": payment_method_line_id,
                                }
                            ],
                            **payment_ctx,
                        )
                        self._execute_odoo(
                            "account.payment.register",
                            "action_create_payments",
                            [[payment_register_id]],
                            **payment_ctx,
                        )
                        payment_registered = True
                        logger.info("create_order: registered payment for account.move id=%s", invoice_id)

                # --- Retrieve total amount ---
                step = "read total"
                if invoice_id:
                    total_data = self._execute_odoo(
                        "account.move", "read", [[invoice_id], ["amount_total"]]
                    )
                else:
                    total_data = self._execute_odoo(
                        "sale.order", "read", [[order_id], ["amount_total"]]
                    )
                total_amount = (total_data[0].get("amount_total") or 0.0) if total_data else 0.0

                message = "Order created and confirmed"
                if invoice_id:
                    message += ", invoice posted"
                if payment_registered:
                    message += ", payment registered"
                message += "."
                result = {
                    "success": True,
                    "message": " ".join([message] + notes),
                    "order_id": order_id,
                    "invoice_id": invoice_id,
                    "total_amount": total_amount,
                }
                return result

            except Exception as e:
                if isinstance(e, xmlrpc.client.Fault):
                    logger.error("XML-RPC Fault in create_order (step: %s): %s", step, e)
                    detail = f"Odoo fault: {e}"
                else:
                    logger.exception("Unexpected error in create_order (step: %s): %s", step, e)
                    detail = f"Unexpected error: {e}"
                if not created:
                    return {"success": False, "step": step, "message": f"Failed at step '{step}': {detail}"}
                return {
                    "success": False,
                    "step": step,
                    "message": (
                        f"Failed at step '{step}' after records were already created: {detail}. "
                        "Do NOT retry create_order (it would duplicate them); inspect and "
                        "finish the listed records in Odoo."
                    ),
                    **created,
                }

        @self.mcp.tool(
            annotations=ToolAnnotations(
                readOnlyHint=False, destructiveHint=False, idempotentHint=False
            )
        )
        def create_customer(
            name: str,
            email: str = "",
            phone: str = "",
            mobile: str = "",
            street: str = "",
            city: str = "",
            country: str = "",
            is_company: bool = False,
        ) -> dict:
            """
            Create a new customer (partner) in Odoo.

            Args:
                name: The customer's name (required).
                email: The customer's email address.
                phone: The customer's phone number.
                mobile: The customer's mobile number.
                street: The customer's street address.
                city: The customer's city.
                country: The country name (e.g., 'Saudi Arabia', 'United States').
                is_company: Whether this is a company (True) or individual (False).

            Returns:
                A dictionary with success status and the new customer's ID.
            """
            if not name or not name.strip():
                return {"success": False, "message": "Customer name is required."}

            try:
                # Check if customer already exists
                existing = self._get_partner_id_by_name(name)
                if existing:
                    return {
                        "success": False,
                        "message": f"A customer with the name '{name}' already exists (ID: {existing}).",
                        "existing_id": existing,
                    }

                partner_data = {
                    "name": name.strip(),
                    "is_company": is_company,
                    "customer_rank": 1,
                }

                if email:
                    partner_data["email"] = email
                if phone:
                    partner_data["phone"] = phone
                if mobile:
                    partner_data["mobile"] = mobile
                if street:
                    partner_data["street"] = street
                if city:
                    partner_data["city"] = city

                # Look up country by name if provided
                if country:
                    countries = self._execute_odoo(
                        "res.country",
                        "search_read",
                        [[("name", "ilike", self._escape_like(country))]],
                        **{"fields": ["id", "name"], "limit": 1},
                    )
                    if countries:
                        partner_data["country_id"] = countries[0]["id"]

                partner_id = self._execute_odoo(
                    "res.partner", "create", [partner_data]
                )
                logger.info("create_customer: created res.partner id=%s", partner_id)
                return {
                    "success": True,
                    "message": f"Customer '{name}' created successfully.",
                    "customer_id": partner_id,
                }
            except Exception as e:
                logger.exception("Error creating customer: %s", e)
                return {"success": False, "message": f"Failed to create customer: {e}"}
