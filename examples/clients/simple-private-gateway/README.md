# Simple Private Gateway Example

A demonstration of how to use the MCP Python SDK as a private gateway with optional API key authentication over streamable HTTP or SSE transport with custom extensions for private gateway connectivity (SNI hostname support).

## Features

- Optional API Key authentication (Bearer token or custom header)
- Supports both StreamableHTTP and SSE transports
- Custom extensions for private gateway (SNI hostname) - **Both transports**
- Can combine authentication + extensions (for authenticated private gateway)
- Interactive command-line interface
- Tool calling

## Installation

```bash
cd examples/clients/simple-private-gateway
uv sync --reinstall 
```

## Usage

### 1. Start an MCP server

You can use any MCP server. For example:

```bash
# Example without authentication - StreamableHTTP transport
cd examples/servers/simple-tool
uv run mcp-simple-tool --transport streamable-http --port 8081

# Or with SSE transport
cd examples/servers/simple-tool
uv run mcp-simple-tool --transport sse --port 8081
```

### 2. Run the client

The client will interactively prompt you for:

- Server URL (or press Enter to configure port/protocol/hostname separately)
  - If you provide a full URL, it will be used directly
  - If you press Enter, you'll be prompted for: port, protocol, and hostname (for SNI)
- Transport type (streamable-http or sse)
- Authentication type (none or API Key)
- For API Key: API key value, header name, and format (Bearer or direct)

```bash
# Run the client interactively
uv run mcp-simple-private-gateway
```

Follow the prompts to configure your connection.

### 3. Use the interactive interface

The client provides several commands:

- `list` - List available tools
- `call <tool_name> [args]` - Call a tool with optional JSON arguments  
- `quit` - Exit

## Examples

### Example 1: Private Gateway without Authentication (StreamableHTTP)

```markdown
🚀 Simple Private Gateway

📝 Server Configuration
==================================================
Server URL [https://localhost:8081]: 
Server port [8081]: 8081
Protocol [https]: https
Server hostname [mcp.deepwiki.com]: mcp.deepwiki.com

Transport type:
  1. streamable-http (default)
  2. sse
Select transport [1]: 1

Authentication:
  1. No authentication (default)
  2. API Key authentication
Select authentication [1]: 1
==================================================

🔗 Connecting to: https://localhost:8081/mcp
📡 Server hostname: mcp.deepwiki.com
🚀 Transport type: streamable-http
🔐 Authentication: None

📡 Opening StreamableHTTP transport connection with extensions...
🤝 Initializing MCP session...
⚡ Starting session initialization...
✨ Session initialization complete!

✅ Connected to MCP server at https://localhost:8081/mcp
Session ID: abc123...

🎯 Interactive MCP Client (Private Gateway)
Commands:
  list - List available tools
  call <tool_name> [args] - Call a tool
  quit - Exit the client

mcp> list
📋 Available tools:
1. echo
   Description: Echo back the input text

mcp> call echo {"text": "Hello, world!"}
🔧 Tool 'echo' result:
Hello, world!

mcp> quit
👋 Goodbye!
```

### Example 2: SSE Transport without Authentication

```markdown
🚀 Simple Private Gateway

📝 Server Configuration
==================================================
Server URL [https://localhost:8081]: 
Server port [8081]: 8081
Protocol [https]: https
Server hostname [mcp.deepwiki.com]: mcp.deepwiki.com

Transport type:
  1. streamable-http (default)
  2. sse
Select transport [1]: 2

Authentication:
  1. No authentication (default)
  2. API Key authentication
Select authentication [1]: 1
==================================================

🔗 Connecting to: https://localhost:8081/sse
📡 Server hostname: mcp.deepwiki.com
🚀 Transport type: sse
🔐 Authentication: None

📡 Opening SSE transport connection with extensions...
🤝 Initializing MCP session...
⚡ Starting session initialization...
✨ Session initialization complete!

✅ Connected to MCP server at https://localhost:8081/sse

🎯 Interactive MCP Client (Private Gateway)
Commands:
  list - List available tools
  call <tool_name> [args] - Call a tool
  quit - Exit the client

mcp> list
📋 Available tools:
1. echo
   Description: Echo back the input text

mcp> quit
👋 Goodbye!
```

### Example 3: API Key Authentication with Bearer Token (StreamableHTTP)

```markdown
🚀 Simple Private Gateway

📝 Server Configuration
==================================================
Server URL [https://localhost:8081]: 
Server port [8081]: 8081
Protocol [https]: https
Server hostname [mcp.deepwiki.com]: api.mcp.example.com

Transport type:
  1. streamable-http (default)
  2. sse
Select transport [1]: 1

Authentication:
  1. No authentication (default)
  2. API Key authentication
Select authentication [1]: 2
Enter API key: sk-1234567890abcdef

API Key format:
  1. Bearer token (Authorization: Bearer <key>) - default
  2. Custom header with key only
Select format [1]: 1
==================================================

🔗 Connecting to: https://localhost:8081/mcp
📡 Server hostname: api.mcp.example.com
🚀 Transport type: streamable-http
🔐 Authentication: API Key
🔑 Header: Authorization
🎯 Format: Bearer token

🔑 Setting up API key authentication (header: Authorization)...
📡 Opening StreamableHTTP transport connection with extensions and apikey auth...
🤝 Initializing MCP session...
⚡ Starting session initialization...
✨ Session initialization complete!

✅ Connected to MCP server at https://localhost:8081/mcp
Session ID: key123...

🎯 Interactive MCP Client (Private Gateway with APIKEY)
Commands:
  list - List available tools
  call <tool_name> [args] - Call a tool
  quit - Exit the client

mcp> list
📋 Available tools:
1. secure-data
   Description: Access secure data with API key

mcp> quit
👋 Goodbye!
```

### Example 4: API Key Authentication with Custom Header (SSE)

```markdown
🚀 Simple Private Gateway

📝 Server Configuration
==================================================
Server URL [https://localhost:8081]: 
Server port [8081]: 8082
Protocol [https]: https
Server hostname [mcp.deepwiki.com]: custom.mcp.example.com

Transport type:
  1. streamable-http (default)
  2. sse
Select transport [1]: 2

Authentication:
  1. No authentication (default)
  2. API Key authentication
Select authentication [1]: 2
Enter API key: my-secret-api-key-123

API Key format:
  1. Bearer token (Authorization: Bearer <key>) - default
  2. Custom header with key only
Select format [1]: 2
Enter header name [X-API-Key]: X-API-Key
==================================================

🔗 Connecting to: https://localhost:8082/sse
📡 Server hostname: custom.mcp.example.com
🚀 Transport type: sse
🔐 Authentication: API Key
🔑 Header: X-API-Key
🎯 Format: Direct key

🔑 Setting up API key authentication (header: X-API-Key)...
📡 Opening SSE transport connection with extensions and apikey auth...
🤝 Initializing MCP session...
⚡ Starting session initialization...
✨ Session initialization complete!

✅ Connected to MCP server at https://localhost:8082/sse

🎯 Interactive MCP Client (Private Gateway with APIKEY)
Commands:
  list - List available tools
  call <tool_name> [args] - Call a tool
  quit - Exit the client

mcp> list
📋 Available tools:
1. api-tool
   Description: Tool requiring custom API key header

mcp> quit
👋 Goodbye!
```

## Configuration

The client uses interactive prompts for configuration. You'll be asked to provide:

- **Server URL**: The full URL of your MCP server (default: <https://localhost:8081>1>)
  - If you provide a URL, it will be used directly
  - If you press Enter (empty), you'll be prompted for individual components:
    - **Server port**: The port where your MCP server is running (default: 8081)
    - **Protocol**: The protocol to use (default: https)
    - **Server hostname**: The hostname for SNI (Server Name Indication) used in private gateway setup (default: mcp.deepwiki.com)
- **Transport type**: Choose between `streamable-http` or `sse` (default: streamable-http)
  - StreamableHTTP servers typically use `/mcp` endpoint
  - SSE servers typically use `/sse` endpoint
- **Authentication**: Choose authentication method (default: no authentication)
  - **None**: No authentication
  - **API Key**: API key-based authentication
    - **API Key**: Your API key value
    - **Format**: Bearer token (Authorization: Bearer <key>) or custom header
    - **Header name**: Custom header name if not using Bearer format (default: X-API-Key)

## Use Cases

This client supports multiple scenarios:

1. **Private Gateway without Auth**: Use custom SNI hostname for HTTPS private gateway connectivity
2. **Private Gateway with API Key**: Use API key authentication (Bearer or custom header) with private gateway
3. **Both Transports**: Works with both StreamableHTTP and SSE transports in all scenarios
