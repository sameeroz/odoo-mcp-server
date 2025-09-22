import os
import re
from mcp.shared.exceptions import McpError, ErrorData

class ConfigValidationError(Exception):
    """Internal exception for config validation failures."""


class OdooConfig:
    """
    Holds required configuration from environment. Validates values on creation.
    """

    _URL_PATTERN = re.compile(r"^https?://")  # simple validation

    def __init__(self):
        # Load from environment (or .env if you use python-dotenv)
        # e.g. from dotenv import load_dotenv; load_dotenv()
        self.odoo_url = os.getenv("ODOO_URL")
        self.odoo_username = os.getenv("ODOO_USERNAME")
        self.odoo_password = os.getenv("ODOO_PASSWORD")
        self.odoo_database = os.getenv("ODOO_DATABASE")

        self._validate()

    def _validate(self):
        missing = []
        if not self.odoo_url:
            missing.append("ODOO_URL")
        if not self.odoo_username:
            missing.append("ODOO_USERNAME")
        if not self.odoo_password:
            missing.append("ODOO_PASSWORD")
        if not self.odoo_database:
            missing.append("ODOO_DATABASE")

        if missing:
            raise ConfigValidationError(f"Missing environment vars: {', '.join(missing)}")

        # Validate URL format
        if not self._URL_PATTERN.match(self.odoo_url):
            raise ConfigValidationError(f"ODOO_URL must start with http:// or https:// - got: {self.odoo_url}")

        # (Optional) Validate password strength or username format
        # if len(self.odoo_username) < 3:
        #     raise ConfigValidationError("ODOO_USERNAME too short (min 3 chars)")
        # if len(self.odoo_password) < 8:
        #     raise ConfigValidationError("ODOO_PASSWORD too short (min 8 chars)")

    def as_dict(self):
        """Return config values, maybe hiding password in logs."""
        return {
            "odoo_url": self.odoo_url,
            "odoo_username": self.odoo_username,
            "odoo_password": "***"  # do not show password
        }

def prepare_error(code: int, message: str, data=None) -> McpError:
    """
    Helper to build an MCPError with given fields.
    """
    errdata = ErrorData(
        code=code,
        message=message,
        data=data
    )
    return McpError(errdata)
