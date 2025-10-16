from typing import Any, List
from openai import OpenAI
from mcp.server.fastmcp import FastMCP
from datetime import datetime
import pytz
import xmlrpc
import traceback


class OdooTools:

    def __init__(self, mcp: FastMCP, config, odoo_server):
        self.mcp = mcp
        self._add_mcp_tools()
        self.config = config
        self.odoo_server = odoo_server

    def _execute_odoo(self, model: str, method: str, args, **kwargs) -> Any:
        """Helper to safely execute Odoo XML-RPC calls."""
        try:
            return self.odoo_server.models.execute_kw(
                self.config.odoo_database,
                self.odoo_server.uid,
                self.config.odoo_password,
                model,
                method,
                args,
                kwargs,
            )
        except Exception as e:
            print(f"[Error] Odoo call failed for {model}.{method}: {e}")
            return []

    def _format_datetime(self, utc_string: str) -> str:
        """Convert UTC time string from Odoo to Riyadh local time."""
        utc_time = datetime.strptime(utc_string, "%Y-%m-%d %H:%M:%S")
        local_tz = pytz.timezone("Asia/Riyadh")
        return (
            utc_time.replace(tzinfo=pytz.utc)
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

    def _get_partner_id_by_name(self, name):
        """
        Fetches the partner ID from Odoo given a contact (customer) name.
        Returns the partner ID if found, otherwise None.
        """
        partners = self._execute_odoo(
            "res.partner",
            "search_read",
            [[["name", "ilike", name]]],
            **{
                "fields": ["id", "name"],
                "limit": 1,
            },
        )
        if partners:
            return partners[0]["id"]
        return None

    def _get_default_journal_and_payment_method(self):
        journals = self._execute_odoo(
            "account.journal",
            "search_read",
            [
                [],
                [
                    "id",
                    "name",
                    "type",
                    "inbound_payment_method_line_ids",
                    "outbound_payment_method_line_ids",
                ],
            ],
        )
        
        for journal in journals:
            if journal["name"] == "Bank" and journal["inbound_payment_method_line_ids"]:
                return journal["id"], journal["inbound_payment_method_line_ids"][0]
            elif journal["name"] == "Cash" and journal["inbound_payment_method_line_ids"]:
                return journal["id"], journal["inbound_payment_method_line_ids"][0]
        return None

    def _add_mcp_tools(self):

        @self.mcp.tool()
        def get_products(product_names_lang: str = "en", limits: int = None) -> dict:
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

            if not products:
                return "No products available."

            return {"products": products}

        @self.mcp.tool()
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

            for lang in language_fallbacks:

                searched_products = self._execute_odoo(
                    "product.product",
                    "search_read",
                    [[["name", "ilike", product_name]]],
                    **{
                        "fields": ["id", "name", "list_price", "description_sale"],
                        "limit": 1,
                        "context": {"lang": (lang)},
                    },
                )

                if searched_products:
                    product_data = searched_products[0]
                    break

            if not product_data:
                return f"No product found with the name: {product_name}"

            return (
                f"Product Name: {product_data['name']}\n"
                f"Price: ${product_data['list_price']}\n"
                f"Description: {product_data.get('description_sale', 'No description available.')}"
            )

        @self.mcp.tool()
        def get_order_details(
            limits=1, order_ids: List[Any] = None, fields: List[str] = None
        ):
            """
            Retrieve and format order details from Odoo.

            Args:
                limit (int): Maximum number of orders to retrieve if order_ids not provided.
                order_ids (List[int], optional): Specific order IDs to fetch.
                fields (List[str], optional): Specific fields to include in the output.
                                            If None, full order details are returned.

            Returns:
                str: Human-readable formatted order details.
            """

            search_domain = [] if order_ids is None else ["id", "in", order_ids]

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

            if not orders:
                return "No orders available."

            results = []
            for order in orders:
                formatted_order = []

                # Common values
                formatted_date = self._format_datetime(order["date_order"])
                order_items = self._get_order_lines(order.get("order_line", []))

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

        @self.mcp.tool()
        def create_order(
            customer_name: str, product_id, create_invoice=False, finish_payment=False
        ) -> dict:
            """
            Securely creates an order in Odoo, generates the corresponding invoice,
            and processes the payment.

            Args:
                product_id (int): The ID of the product to order.
                create_invoice (bool, optional): Flag to determine if an invoice should be created.
                finish_payment (bool, optional): Flag to determine if payment should be processed.

            Returns:
                Dict[str, Any]: A structured result containing success status,
                order/invoice IDs, total amount, and messages.
            """
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

                # --- Check product existance ---
                check_product_existance = self._execute_odoo(
                    "product.product",
                    "search_read",
                    [[["id", "ilike", product_id]]],
                    **{
                        "fields": ["id", "name", "list_price", "description_sale"],
                        "limit": 1,
                    },
                )

                if not check_product_existance:
                    return {
                        "success": False,
                        "message": f"No product found with the ID: {product_id}",
                    }

                # --- Get or validate customer (partner) ---
                partner_id = self._get_partner_id_by_name(customer_name)

                if partner_id is None:
                    return {
                        "success": False,
                        "message": f"No customer found with the name: {customer_name}",
                    }

                # --- Create sales order --
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

                order_line_data = {
                    "order_id": order_id,
                    "product_id": product_id,
                    "product_uom_qty": 1,
                }

                # --- Confirm order ---
                self._execute_odoo("sale.order", "action_confirm", [order_id])

                # --- Create and post invoice ---

                if create_invoice:

                    line_id = self._execute_odoo(
                        "sale.order.line", "create", [order_line_data]
                    )

                    invoice_id = self._execute_odoo(
                        "account.move",
                        "create",
                        [
                            {
                                "move_type": "out_invoice",
                                "partner_id": partner_id,  # Customer being invoiced
                                "invoice_line_ids": [  # --- Create invoice lines ---
                                    (
                                        0,
                                        0,
                                        {
                                            "product_id": product_id,
                                            "quantity": 1,
                                            "sale_line_ids": [(6, 0, [line_id])],
                                        },
                                    )
                                ],
                            }
                        ],
                    )
                    
                    # --- Post the invoice ---
                    self._execute_odoo("account.move", "action_post", [invoice_id])

                    # --- Retrieve total amount ---
                    invoice_data = self._execute_odoo(
                        "account.move", "read", [[invoice_id], ["amount_total"]]
                    )
                    total_amount = invoice_data[0].get("amount_total", 0.0)

                    # --- Register payment ---
                    if finish_payment:
                        
                        # --- Get default journal and payment method ---
                        journal_id, payment_method_line_id = self._get_default_journal_and_payment_method()
                        
                        payment_register_id = self._execute_odoo(
                            "account.payment.register",
                            "create",
                            [
                                {
                                    "journal_id": journal_id,
                                    "payment_method_line_id": payment_method_line_id,
                                }
                            ],
                            **{
                                "context": {
                                    "active_model": "account.move",
                                    "active_ids": [invoice_id],
                                }
                            },
                        )

                        self._execute_odoo(
                            "account.payment.register",
                            "action_create_payments",
                            [[payment_register_id]],
                        )

                    return {
                        "success": True,
                        "message": "Order and invoice created successfully.",
                        "order_id": order_id,
                        "invoice_id": invoice_id,
                        "total_amount": total_amount or 0
                    }

                return {
                    "success": True,
                    "message": "Order created successfully.",
                    "order_id": order_id,
                }

            except xmlrpc.client.Fault as e:
                err_msg = str(e)
                if "Record does not exist or has been deleted" in err_msg:
                    print(f"[Error] Missing product record: {err_msg}")
                    return {
                        "success": False,
                        "message": "One of the products does not exist in Odoo.",
                    }
                print(f"[XML-RPC Fault] {err_msg}")
                return {"success": False, "message": f"Odoo fault: {err_msg}"}

            except Exception as e:
                print(f"[Exception] {e}")
                traceback.print_exc()
                return {"success": False, "message": f"Unexpected error: {e}"}
