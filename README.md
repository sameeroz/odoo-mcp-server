# Odoo MCP Server

[![Python Version](https://img.shields.io/badge/python-3.12+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-orange.svg)](https://modelcontextprotocol.io)

The Odoo MCP Server is a robust and efficient implementation of the Model Context Protocol (MCP) designed to interact seamlessly with Odoo ERP systems. This server provides tools and resources to facilitate integration, automation, and enhanced functionality for Odoo-based workflows.

## 🚀 Features

- **Product Management**: Retrieve product catalogs, search products, and get detailed product information
- **Customer Management**: List, search, and create customers/partners with full contact details
- **Order Processing**: Create sales orders with multi-step workflows and retrieve order details
- **Invoice Generation**: Automatically create and post invoices from sales orders
- **Payment Processing**: Handle payment registration and processing workflows
- **Multi-language Support**: Support for English, Arabic, French, and Spanish product names
- **Configurable Timezone**: Set your preferred timezone via environment variable
- **Structured Logging**: Configurable log levels for debugging and monitoring
- **Secure Authentication**: XML-RPC based authentication with Odoo instances

## 🏗️ Architecture

The project follows a modular architecture with clear separation of concerns:

```
odoo-mcp-server/
├── src/mcpserver/
│   ├── __init__.py          # Package initialization
│   ├── __main__.py          # Application entry point
│   ├── config.py            # Configuration management and validation
│   ├── deployment.py        # MCP server deployment setup
│   ├── odoo_mcp_server.py   # Core server implementation
│   └── tools.py             # MCP tools and Odoo operations
├── pyproject.toml          # Project configuration and dependencies
├── .python-version         # Python version specification
└── README.md               # Project documentation
```

### Core Components

- **OdooMCPServer**: Main server class handling Odoo connections and tool registration
- **OdooConfig**: Configuration management with environment variable validation
- **OdooTools**: Collection of MCP tools for Odoo operations
- **FastMCP**: MCP server framework integration

## 📋 Prerequisites

- Python 3.12 or higher
- Access to an Odoo instance (v17+ recommended)
- Valid Odoo user credentials with appropriate permissions

## 🛠️ Installation

### 1. Install UV

The MCP server runs on your **local computer** (where Claude Desktop is installed), not on your Odoo server. You need to install UV on your local machine:

<details>
<summary>macOS/Linux</summary>

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

</details>

<details>
<summary>Windows</summary>

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

</details>

After installation, restart your terminal to ensure UV is in your PATH.

### 2. Clone the Repository

```bash
git clone git@github.com:sameeroz/odoo-mcp-server.git
cd odoo-mcp-server
```

### 3. Install Dependencies

Using uv:

```bash
uv sync
```

### 4. Installing via MCP Settings

Add this configuration to your MCP settings:

**Using API Key (preferred):**

```json
{
  "mcpServers": {
    "odoo": {
      "command": "uv",
      "args": ["run", "src/mcpserver/__main__.py"],
      "env": {
        "ODOO_URL": "https://your-odoo-instance.com",
        "ODOO_DATABASE": "your-database-name-here",
        "ODOO_API_KEY": "your-api-key-here",
        "ODOO_USERNAME": "your-username-here"
      }
    }
  }
}
```

**Using Username/Password:**

```json
{
  "mcpServers": {
    "odoo": {
      "command": "uv",
      "args": ["run", "src/mcpserver/__main__.py"],
      "env": {
        "ODOO_URL": "https://your-odoo-instance.com",
        "ODOO_DATABASE": "your-database-name-here",
        "ODOO_USERNAME": "your-username-here",
        "ODOO_PASSWORD": "your-password-here"
      }
    }
  }
}
```

<details>
<summary>Claude Desktop</summary>

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "odoo": {
      "command": "uv",
      "args": ["run", "src/mcpserver/__main__.py"],
      "env": {
        "ODOO_URL": "https://your-odoo-instance.com",
        "ODOO_USERNAME": "your-username-here",
        "ODOO_PASSWORD": "your-password-here",
        "ODOO_DATABASE": "your-database-name-here"
      }
    }
  }
}
```

</details>

<details>
<summary>Cursor</summary>

Add to `~/.cursor/mcp_settings.json`:

```json
{
  "mcpServers": {
    "odoo": {
      "command": "uv",
      "args": ["run", "src/mcpserver/__main__.py"],
      "env": {
        "ODOO_URL": "https://your-odoo-instance.com",
        "ODOO_USERNAME": "your-username-here",
        "ODOO_PASSWORD": "your-password-here",
        "ODOO_DATABASE": "your-database-name-here"
      }
    }
  }
}
```

</details>

<details>
<summary>VS Code (with GitHub Copilot)</summary>

Add to your VS Code settings (`~/.vscode/mcp_settings.json` or workspace settings):

```json
{
  "github.copilot.chat.mcpServers": {
    "odoo": {
      "command": "uv",
      "args": ["run", "src/mcpserver/__main__.py"],
      "env": {
        "ODOO_URL": "https://your-odoo-instance.com",
        "ODOO_USERNAME": "your-username-here",
        "ODOO_PASSWORD": "your-password-here",
        "ODOO_DATABASE": "your-database-name-here"
      }
    }
  }
}
```

</details>

<details>
<summary>Zed</summary>

Add to `~/.config/zed/settings.json`:

```json
{
  "context_servers": {
    "odoo": {
      "command": "uv",
      "args": ["run", "src/mcpserver/__main__.py"],
      "env": {
        "ODOO_URL": "https://your-odoo-instance.com",
        "ODOO_USERNAME": "your-username-here",
        "ODOO_PASSWORD": "your-password-here",
        "ODOO_DATABASE": "your-database-name-here"
      }
    }
  }
}
```

</details>

## 🚀 Usage

### Available MCP Tools

#### 1. Product Operations

**`get_products`**

- Retrieve product catalog with optional language and limit parameters
- Supports: English (en), Arabic (ar), French (fr), Spanish (es)

**`get_product_details`**

- Get detailed information for a specific product by name
- Returns: name, price, description

#### 2. Customer Management

**`get_customers`**

- Retrieve a paginated list of customers/partners
- Parameters: limit, offset
- Returns: customer list with contact details and total count

**`search_customers`**

- Search for customers by name, email, phone, or all fields
- Parameters: query, search_by ('name'|'email'|'phone'|'all'), limit

**`create_customer`**

- Create a new customer/partner with full contact details
- Parameters: name, email, phone, mobile, street, city, country, is_company
- Includes duplicate detection

#### 3. Order Management

**`get_order_details`**

- Retrieve sales order information with customizable fields
- Supports filtering by order IDs and field selection

**`create_order`**

- Create new sales orders with automatic invoice and payment processing
- Parameters: customer_name, product_id, create_invoice, finish_payment

### Example Usage in MCP Client

```python
# Get products in Arabic
products = await mcp_client.call_tool("get_products", {
    "product_names_lang": "ar",
    "limits": 10
})

# Search for customers
customers = await mcp_client.call_tool("search_customers", {
    "query": "John",
    "search_by": "all",
    "limit": 5
})

# Create a customer
result = await mcp_client.call_tool("create_customer", {
    "name": "Acme Corp",
    "email": "contact@acme.com",
    "phone": "+1234567890",
    "country": "United States",
    "is_company": True
})

# Create an order with invoice and payment
result = await mcp_client.call_tool("create_order", {
    "customer_name": "John Doe",
    "product_id": 123,
    "create_invoice": True,
    "finish_payment": True
})
```

## ⚙️ Configuration

### Environment Variables

| Variable         | Description              | Required         | Default | Example                 |
| ---------------- | ------------------------ | ---------------- | ------- | ----------------------- |
| `ODOO_URL`       | Odoo instance URL        | Yes              |         | `https://demo.odoo.com` |
| `ODOO_DATABASE`  | Database name            | Yes              |         | `demo_db`               |
| `ODOO_API_KEY`   | Odoo API key (preferred) | If no password   |         | `odoo_api_key_abc123`   |
| `ODOO_USERNAME`  | Odoo username            | Yes (for API key & password) |  | `admin`               |
| `ODOO_PASSWORD`  | Odoo password            | If no API key    |         | `admin123`              |
| `ODOO_TIMEZONE`  | Timezone for dates       | No               | `UTC`   | `Asia/Riyadh`           |
| `ODOO_LOG_LEVEL` | Logging level            | No               | `INFO`  | `DEBUG`                 |

### Validation Rules

- URL must start with `http://` or `https://`
- All environment variables are required
- Connection timeout: 30 seconds

## 🔧 Development

### Key Classes

- `OdooMCPServer`: Main server orchestrator
- `OdooConfig`: Configuration management with validation
- `OdooTools`: MCP tool implementations
- `ConfigValidationError`: Custom exception for configuration errors

### Adding New Tools

To add new MCP tools:

1. Add the tool method to the `OdooTools` class in `tools.py`
2. Use the `@self.mcp.tool()` decorator
3. Include proper type hints and docstrings

## 🔒 Security Considerations

- **Credentials**: Store sensitive information in environment variables
- **Validation**: All inputs are validated before processing
- **Error Handling**: Sensitive information is not exposed in error messages
- **Timeouts**: Connection timeouts prevent hanging requests
- **Permissions**: Ensure Odoo user has minimal required permissions

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Guidelines

- Follow PEP 8 style guidelines
- Add type hints to all functions
- Include comprehensive docstrings
- Write tests for new functionality
- Update documentation as needed

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

- **Issues**: Report bugs and feature requests via GitHub Issues
- **Community**: Join discussions in the project's GitHub Discussions

## 🔗 Related Projects

- [Model Context Protocol](https://modelcontextprotocol.io) - The underlying protocol specification
- [Odoo](https://www.odoo.com) - The ERP system this server integrates with
- [FastMCP](https://github.com/jlowin/fastmcp) - The MCP server framework used

## 📊 Changelog

### v0.2.0 (Current)

- Added customer/partner management tools (get, search, create)
- Added configurable timezone via `ODOO_TIMEZONE` env var
- Added configurable logging via `ODOO_LOG_LEVEL` env var
- Replaced `print()` with structured Python logging
- Fixed order creation flow (order lines now created before confirmation)
- Fixed product ID validation (uses `=` instead of `ilike`)
- Fixed exception handling in connection module
- Fixed domain format in order search
- Added proper type annotations to all tool parameters
- Added `python-dotenv` to dependencies

### v0.1.0

- Initial release
- Basic product and order management tools
- Invoice and payment processing
- Multi-language support

---

**Made with ❤️ by Sameeroz for the MCP and Odoo communities**
