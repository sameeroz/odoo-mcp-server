import http.client
import logging
import xmlrpc.client
from dotenv import load_dotenv
from .tools import OdooTools

logger = logging.getLogger(__name__)
load_dotenv()


class _TimeoutTransport(xmlrpc.client.Transport):
    """HTTP transport that applies a socket timeout (stdlib Transport ignores it)."""

    def __init__(self, timeout, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._timeout = timeout

    def make_connection(self, host):
        if self._connection and host == self._connection[0]:
            return self._connection[1]
        chost, self._extra_headers, x509 = self.get_host_info(host)
        self._connection = host, http.client.HTTPConnection(chost, timeout=self._timeout)
        return self._connection[1]


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    """HTTPS transport that applies a socket timeout."""

    def __init__(self, timeout, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._timeout = timeout

    def make_connection(self, host):
        if self._connection and host == self._connection[0]:
            return self._connection[1]
        chost, self._extra_headers, x509 = self.get_host_info(host)
        self._connection = host, http.client.HTTPSConnection(
            chost, timeout=self._timeout, context=self.context, **(x509 or {})
        )
        return self._connection[1]


def _make_proxy(url, timeout):
    """Create a ServerProxy with its own transport, chosen by URL scheme."""
    transport_cls = _TimeoutSafeTransport if url.lower().startswith("https://") else _TimeoutTransport
    return xmlrpc.client.ServerProxy(url, transport=transport_cls(timeout))


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
        timeout = self.config.odoo_timeout

        try:
            logger.info(
                "Connecting to Odoo at %s with database %s (auth: %s)",
                self.config.odoo_url, self.config.odoo_database, self.config.auth_method
            )
            self.common = _make_proxy(f"{self.config.odoo_url}/xmlrpc/2/common", timeout)
            self.uid = self.common.authenticate(
                self.config.odoo_database, self.config.auth_username, self.config.auth_credential, {}
            )
            if not self.uid:
                raise RuntimeError(
                    "Odoo authentication failed: invalid database, username or credentials "
                    f"(auth: {self.config.auth_method})"
                )
            self.models = _make_proxy(f"{self.config.odoo_url}/xmlrpc/2/object", timeout)
            logger.info("Connected to Odoo as user ID %s (via %s)", self.uid, self.config.auth_method)

        except xmlrpc.client.Fault as e:
            logger.error("XML-RPC Fault: %s - %s", e.faultCode, e.faultString)
            raise
        except TimeoutError:  # socket.timeout is an alias of TimeoutError (3.10+)
            logger.error("Connection to Odoo timed out after %s seconds.", timeout)
            raise
        except Exception as e:
            logger.error("Failed to connect to Odoo: %s", e)
            raise

    def _add_tools(self):
        self.tools = OdooTools(self.mcp, self.config, self)