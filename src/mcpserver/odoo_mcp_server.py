import os
import xmlrpc.client
import socket
from dotenv import load_dotenv
from .tools import OdooTools
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
        print("OdooMCPServer initialized and tools added.")
    def _connect_to_odoo(self):

        # Initialize XML-RPC connections
        # Odoo server connection

        timeout = 30  # seconds
        transport = xmlrpc.client.Transport()
        transport.timeout = timeout

        try:
            print(
                f"Connecting to Odoo at {self.config.odoo_url} with database {self.config.odoo_database} and user {self.config.odoo_username}"
            )
            self.common = xmlrpc.client.ServerProxy(
                f"{self.config.odoo_url}/xmlrpc/2/common", transport=transport
            )
            self.uid = self.common.authenticate(
                self.config.odoo_database, self.config.odoo_username, self.config.odoo_password, {}
            )
            self.models = xmlrpc.client.ServerProxy(
                f"{self.config.odoo_url}/xmlrpc/2/object", transport=transport
            )
            print(f"Connected to Odoo as user ID {self.uid}")

        except xmlrpc.client.Fault as e:
            print(f"XML-RPC Fault: {e.faultCode} - {e.faultString}")
            raise e
        except socket.timeout:
            print("Connection timed out, coulddn't connect to Odoo server.")
            raise e
        except TimeoutError:
            print("TimeoutError: The connection took too long to respond.")
            raise e
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            raise e

    def _add_tools(self):
        self.tools = OdooTools(self.mcp, self.config, self)