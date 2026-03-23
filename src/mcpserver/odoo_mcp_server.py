import os
import logging
import xmlrpc.client
import socket
from dotenv import load_dotenv
from .tools import OdooTools

logger = logging.getLogger(__name__)
load_dotenv()

class OdooMCPServer:

    def __init__(self, mcp, config):
        self.mcp = mcp
        self.common = None
        self.models = None
        self.uid = None

        self.config = config

    def initialize_server(self):
        self._connect_to_odoo()
        self._add_tools()
        logger.info("OdooMCPServer initialized and tools added.")
    def _connect_to_odoo(self):

        # Initialize XML-RPC connections
        # Odoo server connection

        timeout = 30  # seconds
        transport = xmlrpc.client.Transport()
        transport.timeout = timeout

        try:
            logger.info(
                "Connecting to Odoo at %s with database %s (auth: %s)",
                self.config.odoo_url, self.config.odoo_database, self.config.auth_method
            )
            self.common = xmlrpc.client.ServerProxy(
                f"{self.config.odoo_url}/xmlrpc/2/common", transport=transport
            )
            self.uid = self.common.authenticate(
                self.config.odoo_database, self.config.auth_username, self.config.auth_credential, {}
            )
            self.models = xmlrpc.client.ServerProxy(
                f"{self.config.odoo_url}/xmlrpc/2/object", transport=transport
            )
            logger.info("Connected to Odoo as user ID %s (via %s)", self.uid, self.config.auth_method)

        except xmlrpc.client.Fault as e:
            logger.error("XML-RPC Fault: %s - %s", e.faultCode, e.faultString)
            raise e
        except socket.timeout as e:
            logger.error("Connection timed out, couldn't connect to Odoo server.")
            raise e
        except TimeoutError as e:
            logger.error("TimeoutError: The connection took too long to respond.")
            raise e
        except Exception as e:
            logger.error("An unexpected error occurred: %s", e)
            raise e

    def _add_tools(self):
        self.tools = OdooTools(self.mcp, self.config, self)