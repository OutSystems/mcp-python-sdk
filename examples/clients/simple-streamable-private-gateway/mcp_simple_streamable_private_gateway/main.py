#!/usr/bin/env python3
"""
Simple MCP streamable private gateway client example with optional authentication.

This client connects to an MCP server using streamable HTTP or SSE transport
with custom extensions for private gateway connectivity (SNI hostname support)
and optional OAuth authentication.

"""

import asyncio
import threading
import time
import webbrowser
from collections.abc import Callable
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import httpx
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from mcp.shared.message import SessionMessage


class InMemoryTokenStorage(TokenStorage):
    """Simple in-memory token storage implementation."""

    def __init__(self):
        self._tokens: OAuthToken | None = None
        self._client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self._tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self._client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._client_info = client_info


class CallbackHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler to capture OAuth callback."""

    def __init__(self, request: Any, client_address: Any, server: Any, callback_data: dict[str, Any]):
        """Initialize with callback data storage."""
        self.callback_data = callback_data
        super().__init__(request, client_address, server)

    def do_GET(self):
        """Handle GET request from OAuth redirect."""
        parsed = urlparse(self.path)
        query_params = parse_qs(parsed.query)

        if "code" in query_params:
            self.callback_data["authorization_code"] = query_params["code"][0]
            self.callback_data["state"] = query_params.get("state", [None])[0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
            <html>
            <body>
                <h1>Authorization Successful!</h1>
                <p>You can close this window and return to the terminal.</p>
                <script>setTimeout(() => window.close(), 2000);</script>
            </body>
            </html>
            """)
        elif "error" in query_params:
            self.callback_data["error"] = query_params["error"][0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"""
            <html>
            <body>
                <h1>Authorization Failed</h1>
                <p>Error: {query_params["error"][0]}</p>
                <p>You can close this window and return to the terminal.</p>
            </body>
            </html>
            """.encode()
            )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default logging."""
        pass


class CallbackServer:
    """Simple server to handle OAuth callbacks."""

    def __init__(self, port: int = 3000):
        self.port = port
        self.server = None
        self.thread = None
        self.callback_data: dict[str, Any] = {"authorization_code": None, "state": None, "error": None}

    def _create_handler_with_data(self):
        """Create a handler class with access to callback data."""
        callback_data = self.callback_data

        class DataCallbackHandler(CallbackHandler):
            def __init__(self, request: Any, client_address: Any, server: Any):
                super().__init__(request, client_address, server, callback_data)

        return DataCallbackHandler

    def start(self):
        """Start the callback server in a background thread."""
        handler_class = self._create_handler_with_data()
        self.server = HTTPServer(("localhost", self.port), handler_class)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"🖥️  Started callback server on http://localhost:{self.port}")

    def stop(self):
        """Stop the callback server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=1)

    def wait_for_callback(self, timeout: int = 300) -> str:
        """Wait for OAuth callback with timeout."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.callback_data["authorization_code"]:
                return self.callback_data["authorization_code"]
            elif self.callback_data["error"]:
                raise Exception(f"OAuth error: {self.callback_data['error']}")
            time.sleep(0.1)
        raise Exception("Timeout waiting for OAuth callback")

    def get_state(self):
        """Get the received state parameter."""
        return self.callback_data["state"]


class APIKeyAuth(httpx.Auth):
    """Custom httpx Auth class for API key authentication."""

    def __init__(self, api_key: str, header_name: str = "Authorization", use_bearer: bool = True):
        self.api_key = api_key
        self.header_name = header_name
        self.use_bearer = use_bearer

    def auth_flow(self, request: httpx.Request):
        """Add API key to request headers."""
        if self.use_bearer:
            request.headers[self.header_name] = f"Bearer {self.api_key}"
        else:
            request.headers[self.header_name] = self.api_key
        yield request


class SimpleStreamablePrivateGateway:
    """Simple MCP private gateway client supporting StreamableHTTP and SSE transports.

    This client demonstrates how to use custom extensions (e.g., SNI hostname) for
    private gateway connectivity with both transport types, with optional authentication
    (OAuth or API key).
    """

    def __init__(
        self,
        server_url: str,
        server_hostname: str,
        transport_type: str = "streamable-http",
        auth_type: str = "none",
        api_key: str | None = None,
        api_key_header: str = "Authorization",
        use_bearer: bool = True,
        client_metadata_url: str | None = None,
    ):
        self.server_url = server_url
        self.server_hostname = server_hostname
        self.transport_type = transport_type
        self.auth_type = auth_type
        self.api_key = api_key
        self.api_key_header = api_key_header
        self.use_bearer = use_bearer
        self.client_metadata_url = client_metadata_url
        self.session: ClientSession | None = None

    async def connect(self):
        """Connect to the MCP server."""
        print(f"🔗 Attempting to connect to {self.server_url}...")

        callback_server: CallbackServer | None = None
        try:
            # Set up authentication if needed
            auth = None

            if self.auth_type == "oauth":
                print("🔐 Setting up OAuth authentication...")
                callback_server = CallbackServer(port=3030)
                callback_server.start()

                async def callback_handler() -> tuple[str, str | None]:
                    """Wait for OAuth callback and return auth code and state."""
                    print("⏳ Waiting for authorization callback...")
                    try:
                        auth_code = callback_server.wait_for_callback(timeout=300)
                        return auth_code, callback_server.get_state()
                    finally:
                        callback_server.stop()

                client_metadata_dict = {
                    "client_name": "Simple Private Gateway Client",
                    "redirect_uris": ["http://localhost:3030/callback"],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                }

                async def _default_redirect_handler(authorization_url: str) -> None:
                    """Default redirect handler that opens the URL in a browser."""
                    print(f"Opening browser for authorization: {authorization_url}")
                    webbrowser.open(authorization_url)

                # Create OAuth authentication handler
                auth = OAuthClientProvider(
                    server_url=self.server_url,
                    client_metadata=OAuthClientMetadata.model_validate(client_metadata_dict),
                    storage=InMemoryTokenStorage(),
                    redirect_handler=_default_redirect_handler,
                    callback_handler=callback_handler,
                    client_metadata_url=self.client_metadata_url,
                )
            elif self.auth_type == "apikey":
                if not self.api_key:
                    raise ValueError("API key is required for API key authentication")
                print(f"🔑 Setting up API key authentication (header: {self.api_key_header})...")
                auth = APIKeyAuth(
                    api_key=self.api_key,
                    header_name=self.api_key_header,
                    use_bearer=self.use_bearer,
                )

            # Create transport based on transport type
            if self.transport_type == "sse":
                if auth:
                    print(f"📡 Opening SSE transport connection with extensions and {self.auth_type} auth...")
                else:
                    print("📡 Opening SSE transport connection with extensions...")
                # SSE transport with custom extensions for private gateway
                async with sse_client(
                    url=self.server_url,
                    headers={"Host": self.server_hostname},
                    extensions={"sni_hostname": self.server_hostname},
                    auth=auth,
                    timeout=60,
                ) as (read_stream, write_stream):
                    await self._run_session(read_stream, write_stream, None)
            else:
                if auth:
                    print(
                        f"📡 Opening StreamableHTTP transport connection with extensions and {self.auth_type} auth..."
                    )
                else:
                    print("📡 Opening StreamableHTTP transport connection with extensions...")
                # Note: terminate_on_close=False prevents SSL handshake failures during exit
                # Some servers may not handle session termination gracefully over SSL
                async with streamablehttp_client(
                    url=self.server_url,
                    headers={"Host": self.server_hostname},
                    extensions={"sni_hostname": self.server_hostname},
                    auth=auth,
                    timeout=timedelta(seconds=60),
                    terminate_on_close=False,  # Skip session termination to avoid SSL errors
                ) as (read_stream, write_stream, get_session_id):
                    await self._run_session(read_stream, write_stream, get_session_id)

        except Exception as e:
            print(f"❌ Failed to connect: {e}")
            import traceback

            traceback.print_exc()
        finally:
            # Clean up callback server if it was started
            if callback_server:
                callback_server.stop()

    async def _run_session(
        self,
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
        get_session_id: Callable[[], str | None] | None,
    ):
        """Run the MCP session with the given streams."""
        print("🤝 Initializing MCP session...")
        async with ClientSession(read_stream, write_stream) as session:
            self.session = session
            print("⚡ Starting session initialization...")
            await session.initialize()
            print("✨ Session initialization complete!")

            print(f"\n✅ Connected to MCP server at {self.server_url}")
            if get_session_id:
                session_id = get_session_id()
                if session_id:
                    print(f"Session ID: {session_id}")

            # Run interactive loop
            await self.interactive_loop()

    async def list_tools(self):
        """List available tools from the server."""
        if not self.session:
            print("❌ Not connected to server")
            return

        try:
            result = await self.session.list_tools()
            if hasattr(result, "tools") and result.tools:
                print("\n📋 Available tools:")
                for i, tool in enumerate(result.tools, 1):
                    print(f"{i}. {tool.name}")
                    if tool.description:
                        print(f"   Description: {tool.description}")
                    print()
            else:
                print("No tools available")
        except Exception as e:
            print(f"❌ Failed to list tools: {e}")

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None):
        """Call a specific tool."""
        if not self.session:
            print("❌ Not connected to server")
            return

        try:
            result = await self.session.call_tool(tool_name, arguments or {})
            print(f"\n🔧 Tool '{tool_name}' result:")
            if hasattr(result, "content"):
                for content in result.content:
                    if content.type == "text":
                        print(content.text)
                    else:
                        print(content)
            else:
                print(result)
        except Exception as e:
            print(f"❌ Failed to call tool '{tool_name}': {e}")

    async def interactive_loop(self):
        """Run interactive command loop."""
        auth_status = f" with {self.auth_type.upper()}" if self.auth_type != "none" else ""
        print(f"\n🎯 Interactive MCP Client (Private Gateway{auth_status})")
        print("Commands:")
        print("  list - List available tools")
        print("  call <tool_name> [args] - Call a tool")
        print("  quit - Exit the client")
        print()

        while True:
            try:
                command = input("mcp> ").strip()

                if not command:
                    continue

                if command == "quit":
                    print("👋 Goodbye!")
                    break

                elif command == "list":
                    await self.list_tools()

                elif command.startswith("call "):
                    parts = command.split(maxsplit=2)
                    tool_name = parts[1] if len(parts) > 1 else ""

                    if not tool_name:
                        print("❌ Please specify a tool name")
                        continue

                    # Parse arguments (simple JSON-like format)
                    arguments: dict[str, Any] | None = None
                    if len(parts) > 2:
                        import json

                        try:
                            parsed = json.loads(parts[2])
                            if isinstance(parsed, dict):
                                arguments = cast(dict[str, Any], parsed)
                        except json.JSONDecodeError:
                            print("❌ Invalid arguments format (expected JSON)")
                            continue

                    await self.call_tool(tool_name, arguments)

                else:
                    print("❌ Unknown command. Try 'list', 'call <tool_name>', or 'quit'")

            except KeyboardInterrupt:
                print("\n\n👋 Goodbye!")
                break
            except EOFError:
                print("\n👋 Goodbye!")
                break


def get_user_input():
    """Get server configuration from user input."""
    print("🚀 Simple Streamable Private Gateway")
    print("\n📝 Server Configuration")
    print("=" * 50)

    # Get server port
    server_port = input("Server port [8081]: ").strip() or "8081"

    # Get server hostname
    server_hostname = input("Server hostname [mcp.deepwiki.com]: ").strip() or "mcp.deepwiki.com"

    # Get transport type
    print("\nTransport type:")
    print("  1. streamable-http (default)")
    print("  2. sse")
    transport_choice = input("Select transport [1]: ").strip() or "1"

    if transport_choice == "2":
        transport_type = "sse"
    else:
        transport_type = "streamable-http"

    # Get authentication preference
    print("\nAuthentication:")
    print("  1. No authentication (default)")
    print("  2. OAuth authentication")
    print("  3. API Key authentication")
    auth_choice = input("Select authentication [1]: ").strip() or "1"

    auth_type = "none"
    api_key = None
    api_key_header = "Authorization"
    use_bearer = True
    client_metadata_url = None

    if auth_choice == "2":
        auth_type = "oauth"
        client_metadata_url = input("Client metadata URL (optional, press Enter to skip): ").strip() or None
    elif auth_choice == "3":
        auth_type = "apikey"
        api_key = input("Enter API key: ").strip()

        # Ask for header configuration
        print("\nAPI Key format:")
        print("  1. Bearer token (Authorization: Bearer <key>) - default")
        print("  2. Custom header with key only")
        format_choice = input("Select format [1]: ").strip() or "1"

        if format_choice == "2":
            use_bearer = False
            api_key_header = input("Enter header name [X-API-Key]: ").strip() or "X-API-Key"

    print("=" * 50)

    return (
        server_port,
        server_hostname,
        transport_type,
        auth_type,
        api_key,
        api_key_header,
        use_bearer,
        client_metadata_url,
    )


async def main():
    """Main entry point."""
    try:
        # Get configuration from user input
        (
            server_port,
            server_hostname,
            transport_type,
            auth_type,
            api_key,
            api_key_header,
            use_bearer,
            client_metadata_url,
        ) = get_user_input()

        # Set URL endpoint based on transport type
        # StreamableHTTP servers typically use /mcp, SSE servers use /sse
        endpoint = "/mcp" if transport_type == "streamable-http" else "/sse"
        # Use http when auth is enabled (typical for OAuth), https for private gateway
        protocol = "http" if auth_type == "oauth" else "https"
        server_url = f"{protocol}://localhost:{server_port}{endpoint}"

        print(f"\n🔗 Connecting to: {server_url}")
        print(f"📡 Server hostname: {server_hostname}")
        print(f"🚀 Transport type: {transport_type}")

        if auth_type == "oauth":
            print("🔐 Authentication: OAuth")
            if client_metadata_url:
                print(f"📋 Client metadata URL: {client_metadata_url}")
        elif auth_type == "apikey":
            print("🔐 Authentication: API Key")
            print(f"🔑 Header: {api_key_header}")
            print(f"🎯 Format: {'Bearer token' if use_bearer else 'Direct key'}")
        else:
            print("🔐 Authentication: None")
        print()

        # Start connection flow
        client = SimpleStreamablePrivateGateway(
            server_url=server_url,
            server_hostname=server_hostname,
            transport_type=transport_type,
            auth_type=auth_type,
            api_key=api_key,
            api_key_header=api_key_header,
            use_bearer=use_bearer,
            client_metadata_url=client_metadata_url,
        )
        await client.connect()

    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
    except EOFError:
        print("\n👋 Goodbye!")


def cli():
    """CLI entry point for uv script."""
    asyncio.run(main())


if __name__ == "__main__":
    cli()
