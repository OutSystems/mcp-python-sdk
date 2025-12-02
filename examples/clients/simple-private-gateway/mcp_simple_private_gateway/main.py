#!/usr/bin/env python3
"""
Simple MCP private gateway client example with optional API key authentication.

This client connects to an MCP server using streamable HTTP or SSE transport
with custom extensions for private gateway connectivity (SNI hostname support)
and optional API key authentication.

"""

import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import Any, cast

import httpx
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.message import SessionMessage


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


class SimplePrivateGateway:
    """Simple MCP private gateway client supporting StreamableHTTP and SSE transports.

    This client demonstrates how to use custom extensions (e.g., SNI hostname) for
    private gateway connectivity with both transport types, with optional API key authentication.
    """

    def __init__(
        self,
        server_url: str,
        server_hostname: str | None,
        transport_type: str = "streamable-http",
        use_api_key: bool = False,
        api_key: str | None = None,
        api_key_header: str = "Authorization",
        use_bearer: bool = True,
    ):
        self.server_url = server_url
        self.server_hostname = server_hostname
        self.transport_type = transport_type
        self.use_api_key = use_api_key
        self.api_key = api_key
        self.api_key_header = api_key_header
        self.use_bearer = use_bearer
        self.session: ClientSession | None = None

    async def connect(self):
        """Connect to the MCP server."""
        print(f"🔗 Attempting to connect to {self.server_url}...")

        try:
            # Set up authentication if needed
            auth = None

            if self.use_api_key:
                if not self.api_key:
                    raise ValueError("API key is required for API key authentication")
                print(f"🔑 Setting up API key authentication (header: {self.api_key_header})...")
                auth = APIKeyAuth(
                    api_key=self.api_key,
                    header_name=self.api_key_header,
                    use_bearer=self.use_bearer,
                )

            if self.server_hostname:
                headers = {"Host": self.server_hostname}
                extensions = {"sni_hostname": self.server_hostname}
            else:
                headers = None
                extensions = None

            # Create transport based on transport type
            if self.transport_type == "sse":
                if auth:
                    print("📡 Opening SSE transport connection with extensions and API key auth...")
                else:
                    print("📡 Opening SSE transport connection with extensions...")
                # SSE transport with custom extensions for private gateway

                async with sse_client(
                    url=self.server_url,
                    headers=headers,
                    extensions=extensions,
                    auth=auth,
                    timeout=60,
                ) as (read_stream, write_stream):
                    await self._run_session(read_stream, write_stream, None)
                
            else:
                if auth:
                    print("📡 Opening StreamableHTTP transport connection with extensions and API key auth...")
                else:
                    print("📡 Opening StreamableHTTP transport connection with extensions...")
                # Note: terminate_on_close=False prevents SSL handshake failures during exit
                # Some servers may not handle session termination gracefully over SSL
                
                async with streamablehttp_client(
                    url=self.server_url,
                    headers=headers,
                    extensions=extensions,
                    auth=auth,
                    timeout=timedelta(seconds=60),
                    terminate_on_close=False,  # Skip session termination to avoid SSL errors
                ) as (read_stream, write_stream, get_session_id):
                    await self._run_session(read_stream, write_stream, get_session_id)

        except Exception as e:
            print(f"❌ Failed to connect: {e}")
            import traceback

            traceback.print_exc()

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
        auth_status = " with API Key" if self.use_api_key else ""
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
    print("🚀 Simple Private Gateway")
    print("\n📝 Server Configuration")
    print("=" * 50)

    # Get server url
    server_url = input("Server URL [https://localhost:8081]: ").strip() or None
    server_port = None
    server_hostname = None    

    # Get transport type
    print("\nTransport type:")
    print("  1. streamable-http (default)")
    print("  2. sse")
    transport_choice = input("Select transport [1]: ").strip() or "1"

    if transport_choice == "2":
        transport_type = "sse"
    else:
        transport_type = "streamable-http"

    # Set URL endpoint based on transport type
    # StreamableHTTP servers typically use /mcp, SSE servers use /sse
    endpoint = "/mcp" if transport_type == "streamable-http" else "/sse"

    if server_url is None:
        # Get server port
        server_port = input("Server port [8081]: ").strip() or "8081"
        protocol = input("Protocol [https]: ").strip() or "https"
        server_url = f"{protocol}://localhost:{server_port}{endpoint}"

        # Get server hostname
        server_hostname = input("Server hostname [mcp.deepwiki.com]: ").strip() or "mcp.deepwiki.com"

    # Get authentication preference
    print("\nAuthentication:")
    print("  1. No authentication (default)")
    print("  2. API Key authentication")
    auth_choice = input("Select authentication [1]: ").strip() or "1"

    use_api_key = False
    api_key = None
    api_key_header = "Authorization"
    use_bearer = True

    if auth_choice == "2":
        use_api_key = True
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
        use_api_key,
        api_key,
        api_key_header,
        use_bearer,
        server_url,
    )


async def main():
    """Main entry point."""
    try:
        # Get configuration from user input
        (
            server_port,
            server_hostname,
            transport_type,
            use_api_key,
            api_key,
            api_key_header,
            use_bearer,
            server_url,
        ) = get_user_input()
        
        print(f"\n🔗 Connecting to: {server_url}")     
        print(f"📡 Server hostname: {server_hostname}")
        print(f"🚀 Transport type: {transport_type}")

        if use_api_key:
            print("🔐 Authentication: API Key")
            print(f"🔑 Header: {api_key_header}")
            print(f"🎯 Format: {'Bearer token' if use_bearer else 'Direct key'}")
        else:
            print("🔐 Authentication: None")
        print()

        # Start connection flow
        client = SimplePrivateGateway(
            server_url=server_url,
            server_hostname=server_hostname,
            transport_type=transport_type,
            use_api_key=use_api_key,
            api_key=api_key,
            api_key_header=api_key_header,
            use_bearer=use_bearer,
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
