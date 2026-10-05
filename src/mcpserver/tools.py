from typing import Any, List
from mcp.server.fastmcp import FastMCP
from datetime import datetime
import logging
import pytz
import xmlrpc.client

logger = logging.getLogger(__name__)


class OdooTools:

    def __init__(self, mcp: FastMCP, config, odoo_server):
        self.mcp = mcp
        self._add_mcp_tools()
        self.config = config
        self.odoo_server = odoo_server

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

    def _format_datetime(self, utc_string: str) -> str:
        """Convert UTC time string from Odoo to configured local time."""
        utc_time = datetime.strptime(utc_string, "%Y-%m-%d %H:%M:%S")
        local_tz = pytz.timezone(self.config.odoo_timezone)
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
        return None, None

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

            try:
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
            except Exception as e:
                return f"Error: failed to retrieve product details: {e}"

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

        @self.mcp.tool()
        def create_order(
            customer_name: str, product_id: int, create_invoice: bool = False, finish_payment: bool = False
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

                # --- Check product existence ---
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

                # --- Create order line BEFORE confirming ---
                line_id = self._execute_odoo(
                    "sale.order.line", "create", [order_line_data]
                )

                # --- Confirm order ---
                self._execute_odoo("sale.order", "action_confirm", [order_id])

                # --- Create and post invoice ---

                if create_invoice:

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
                    logger.error("Missing product record: %s", err_msg)
                    return {
                        "success": False,
                        "message": "One of the products does not exist in Odoo.",
                    }
                logger.error("XML-RPC Fault: %s", err_msg)
                return {"success": False, "message": f"Odoo fault: {err_msg}"}

            except Exception as e:
                logger.exception("Unexpected error creating order: %s", e)
                return {"success": False, "message": f"Unexpected error: {e}"}

        @self.mcp.tool()
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

        @self.mcp.tool()
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

            search_fields = {
                "name": [["name", "ilike", query]],
                "email": [["email", "ilike", query]],
                "phone": ["|", ["phone", "ilike", query], ["mobile", "ilike", query]],
                "all": [
                    "|", "|", "|",
                    ["name", "ilike", query],
                    ["email", "ilike", query],
                    ["phone", "ilike", query],
                    ["mobile", "ilike", query],
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

        @self.mcp.tool()
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
                        [[("name", "ilike", country)]],
                        **{"fields": ["id", "name"], "limit": 1},
                    )
                    if countries:
                        partner_data["country_id"] = countries[0]["id"]

                partner_id = self._execute_odoo(
                    "res.partner", "create", [partner_data]
                )
                return {
                    "success": True,
                    "message": f"Customer '{name}' created successfully.",
                    "customer_id": partner_id,
                }
            except Exception as e:
                logger.exception("Error creating customer: %s", e)
                return {"success": False, "message": f"Failed to create customer: {e}"}
