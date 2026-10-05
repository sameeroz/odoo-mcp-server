import pytest

from mcpserver.config import DEFAULT_TIMEOUT, ConfigValidationError, OdooConfig


def test_valid_api_key_config():
    cfg = OdooConfig()
    assert cfg.auth_method == "api_key"
    assert cfg.auth_credential == "key"
    assert cfg.odoo_timeout == DEFAULT_TIMEOUT
    assert cfg.odoo_read_only is False
    assert cfg.odoo_timezone == "UTC"
    assert cfg.odoo_payment_journal is None


@pytest.mark.parametrize("var", ["ODOO_URL", "ODOO_DATABASE"])
def test_missing_required(monkeypatch, var):
    monkeypatch.delenv(var)
    with pytest.raises(ConfigValidationError, match=var):
        OdooConfig()


def test_all_missing(monkeypatch):
    for var in ("ODOO_URL", "ODOO_DATABASE"):
        monkeypatch.delenv(var)
    with pytest.raises(ConfigValidationError, match="ODOO_URL, ODOO_DATABASE"):
        OdooConfig()


@pytest.mark.parametrize("url", ["odoo.test", "ftp://odoo.test", "//odoo.test"])
def test_bad_url(monkeypatch, url):
    monkeypatch.setenv("ODOO_URL", url)
    with pytest.raises(ConfigValidationError, match="http"):
        OdooConfig()


def test_password_auth(monkeypatch):
    monkeypatch.delenv("ODOO_API_KEY")
    monkeypatch.setenv("ODOO_PASSWORD", "pw")
    cfg = OdooConfig()
    assert cfg.auth_method == "password"
    assert cfg.auth_credential == "pw"
    assert cfg.auth_username == "user"


def test_api_key_preferred_over_password(monkeypatch):
    monkeypatch.setenv("ODOO_PASSWORD", "pw")
    assert OdooConfig().auth_credential == "key"


def test_no_auth(monkeypatch):
    monkeypatch.delenv("ODOO_API_KEY")
    with pytest.raises(ConfigValidationError, match="Authentication required"):
        OdooConfig()


def test_username_without_password(monkeypatch):
    monkeypatch.delenv("ODOO_API_KEY")
    with pytest.raises(ConfigValidationError, match="Authentication required"):
        OdooConfig()


def test_password_without_username(monkeypatch):
    monkeypatch.delenv("ODOO_API_KEY")
    monkeypatch.delenv("ODOO_USERNAME")
    monkeypatch.setenv("ODOO_PASSWORD", "pw")
    with pytest.raises(ConfigValidationError, match="Authentication required"):
        OdooConfig()


@pytest.mark.parametrize("raw, expected", [("60", 60.0), ("0.5", 0.5), (" 5 ", 5.0), ("", 30), ("  ", 30)])
def test_timeout_valid(monkeypatch, raw, expected):
    monkeypatch.setenv("ODOO_TIMEOUT", raw)
    assert OdooConfig().odoo_timeout == expected


@pytest.mark.parametrize("raw", ["abc", "0", "-3"])
def test_timeout_invalid(monkeypatch, raw):
    monkeypatch.setenv("ODOO_TIMEOUT", raw)
    with pytest.raises(ConfigValidationError, match="ODOO_TIMEOUT"):
        OdooConfig()


@pytest.mark.parametrize(
    "raw, expected",
    [("true", True), ("TRUE", True), ("1", True), ("yes", True), ("false", False),
     ("0", False), ("no", False), ("", False), ("  ", False)],
)
def test_read_only_valid(monkeypatch, raw, expected):
    monkeypatch.setenv("ODOO_READ_ONLY", raw)
    assert OdooConfig().odoo_read_only is expected


def test_read_only_invalid(monkeypatch):
    monkeypatch.setenv("ODOO_READ_ONLY", "maybe")
    with pytest.raises(ConfigValidationError, match="ODOO_READ_ONLY"):
        OdooConfig()


def test_payment_journal(monkeypatch):
    monkeypatch.setenv("ODOO_PAYMENT_JOURNAL", " BNK1 ")
    assert OdooConfig().odoo_payment_journal == "BNK1"
    monkeypatch.setenv("ODOO_PAYMENT_JOURNAL", "   ")
    assert OdooConfig().odoo_payment_journal is None


def test_timezone_valid(monkeypatch):
    monkeypatch.setenv("ODOO_TIMEZONE", "Asia/Riyadh")
    assert OdooConfig().odoo_timezone == "Asia/Riyadh"


@pytest.mark.parametrize("tz", ["Mars/Base", "../etc/passwd", ""])
def test_timezone_invalid(monkeypatch, tz):
    monkeypatch.setenv("ODOO_TIMEZONE", tz)
    with pytest.raises(ConfigValidationError, match="ODOO_TIMEZONE"):
        OdooConfig()
