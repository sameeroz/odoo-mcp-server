import logging
import os
import sys
from mcpserver.deployment import mcp
from mcpserver.odoo_mcp_server import OdooMCPServer
from mcp.shared.exceptions import McpError
from mcpserver.config import OdooConfig, ConfigValidationError

# Configure logging
log_level = os.getenv("ODOO_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def main() -> int:
    try:
        config = OdooConfig()
        server = OdooMCPServer(mcp, config)
        server.initialize_server()
        mcp.run()
        return 0

    except ConfigValidationError as cfg_err:
        print(f"Configuration validation error: {cfg_err}", file=sys.stderr)
        return 1
    except McpError as e:
        # You can log it on server
        logger.error("[MCP Server Error] %s", e)
        return 1
    except KeyboardInterrupt:
        logger.info("Server stopped by user.")
        return 0
    except ValueError as e:
        # Configuration errors
        logger.error("Configuration error: %s", e)
        logger.error("Please check your environment variables or .env file")
        return 1
    except Exception:
        logger.exception("Error running OdooMCPServer")
        return 1


if __name__ == "__main__":
    sys.exit(main())
