import os
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEOUT = 30  # seconds


class ConfigValidationError(Exception):
    """Internal exception for config validation failures."""


class OdooConfig:
    """
    Holds required configuration from environment. Validates values on creation.
    Supports two authentication methods:
      1. API Key (preferred) — set ODOO_API_KEY
      2. Username/Password (fallback) — set ODOO_USERNAME and ODOO_PASSWORD
    """

    _URL_PATTERN = re.compile(r"^https?://")  # simple validation

    def __init__(self):
        self.odoo_url = os.getenv("ODOO_URL")
        self.odoo_database = os.getenv("ODOO_DATABASE")
        self.odoo_timezone = os.getenv("ODOO_TIMEZONE", "UTC")
        self.odoo_timeout = self._parse_timeout(os.getenv("ODOO_TIMEOUT"))
        self.odoo_read_only = self._parse_bool("ODOO_READ_ONLY", os.getenv("ODOO_READ_ONLY"))
        # Journal (name or code) used for payments; None = first bank/cash journal
        self.odoo_payment_journal = (os.getenv("ODOO_PAYMENT_JOURNAL") or "").strip() or None

        # Auth method 1: API key (preferred)
        self.odoo_api_key = os.getenv("ODOO_API_KEY")

        # Auth method 2: Username/password (fallback)
        self.odoo_username = os.getenv("ODOO_USERNAME")
        self.odoo_password = os.getenv("ODOO_PASSWORD")

        self._validate()

    @staticmethod
    def _parse_timeout(raw: str | None) -> float:
        """Parse ODOO_TIMEOUT (seconds); defaults to DEFAULT_TIMEOUT when unset."""
        if raw is None or raw.strip() == "":
            return DEFAULT_TIMEOUT
        try:
            value = float(raw)
        except ValueError:
            raise ConfigValidationError(f"ODOO_TIMEOUT must be a number of seconds - got: {raw}")
        if value <= 0:
            raise ConfigValidationError(f"ODOO_TIMEOUT must be greater than 0 - got: {raw}")
        return value

    @staticmethod
    def _parse_bool(var: str, raw: str | None, default: bool = False) -> bool:
        """Parse a boolean env var (true/false/1/0/yes/no); defaults when unset or empty."""
        if raw is None or raw.strip() == "":
            return default
        value = raw.strip().lower()
        if value in ("true", "1", "yes"):
            return True
        if value in ("false", "0", "no"):
            return False
        raise ConfigValidationError(f"{var} must be one of true/false/1/0/yes/no - got: {raw}")

    @property
    def auth_method(self) -> str:
        """Returns the active authentication method: 'api_key' or 'password'."""
        if self.odoo_api_key:
            return "api_key"
        return "password"

    @property
    def auth_credential(self) -> str:
        """Returns the credential to use for XML-RPC calls (API key or password)."""
        if self.odoo_api_key:
            return str(self.odoo_api_key)
        return self.odoo_password or ""

    @property
    def auth_username(self) -> str:
        """Returns the username for authentication.
        With API key auth, the username is still needed for XML-RPC authenticate()."""
        return self.odoo_username or ""

    def _validate(self):
        missing = []
        if not self.odoo_url:
            missing.append("ODOO_URL")
        if not self.odoo_database:
            missing.append("ODOO_DATABASE")

        if missing:
            raise ConfigValidationError(f"Missing environment vars: {', '.join(missing)}")

        # Validate URL format
        if not self._URL_PATTERN.match(self.odoo_url):
            raise ConfigValidationError(f"ODOO_URL must start with http:// or https:// - got: {self.odoo_url}")

        # Validate timezone
        try:
            ZoneInfo(self.odoo_timezone)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise ConfigValidationError(f"ODOO_TIMEZONE is not a valid timezone name - got: {self.odoo_timezone}")

        # Must have either API key OR username+password
        has_api_key = bool(self.odoo_api_key)
        has_credentials = bool(self.odoo_username) and bool(self.odoo_password)

        if not has_api_key and not has_credentials:
            raise ConfigValidationError(
                "Authentication required: set ODOO_API_KEY (preferred) "
                "or both ODOO_USERNAME and ODOO_PASSWORD"
            )
