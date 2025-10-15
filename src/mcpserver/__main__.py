from mcpserver.deployment import mcp
from mcpserver.odoo_mcp_server import OdooMCPServer
from mcp.shared.exceptions import McpError
from mcpserver.config import OdooConfig, ConfigValidationError
import sys


def main():
    try:
        config = OdooConfig()
        server = OdooMCPServer(mcp, config)
        server.initialize_server()
        mcp.run()

    except ConfigValidationError as cfg_err:
        print(f"Configuration validation error: {cfg_err}", file=sys.stderr)
    except McpError as e:
        # You can log it on server
        print("[MCP Server Error]", e)
        return 1
    except KeyboardInterrupt:
        print("Server stopped by user.")
        return "Server stopped."
    except ValueError as e:
        # Configuration errors
        print(f"Configuration error: {e}", file=sys.stderr)
        print("\nPlease check your environment variables or .env file", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error initializing OdooMCPServer: {e}")
        raise e


if __name__ == "__main__":
    main()
