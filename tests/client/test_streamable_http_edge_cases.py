"""
Tests for edge cases and error paths in StreamableHTTP client transport.

This file specifically tests error handling, edge cases, and less common code paths
to achieve 100% code coverage for the streamable_http client module.
"""

import json
from unittest.mock import AsyncMock, Mock, patch

import anyio
import httpx
import pytest
from httpx_sse import ServerSentEvent

from mcp.client.streamable_http import ResumptionError, StreamableHTTPTransport
from mcp.shared.message import ClientMessageMetadata, SessionMessage
from mcp.types import JSONRPCError, JSONRPCMessage, JSONRPCNotification, JSONRPCRequest, JSONRPCResponse


class TestStreamableHTTPEdgeCases:
    """Test edge cases and error handling in StreamableHTTP transport."""

    def test_maybe_extract_protocol_version_invalid_result(self):
        """Test protocol version extraction with invalid InitializeResult."""
        transport = StreamableHTTPTransport("http://test.example.com")

        # Create a response with invalid result structure using model_construct to bypass validation
        response = JSONRPCResponse.model_construct(
            jsonrpc="2.0",
            id="test-id",
            result={"invalid": "structure"},  # Missing required InitializeResult fields
        )
        invalid_message = JSONRPCMessage(response)

        # Should handle exception gracefully and log warning
        transport._maybe_extract_protocol_version_from_message(invalid_message)

        # Protocol version should remain None since extraction failed
        assert transport.protocol_version is None

    def test_maybe_extract_protocol_version_non_dict_result(self):
        """Test protocol version extraction with non-dict result."""
        transport = StreamableHTTPTransport("http://test.example.com")

        # Create a response with non-dict result using model_construct
        response = JSONRPCResponse.model_construct(
            jsonrpc="2.0",
            id="test-id",
            result="string result",  # Invalid: should be dict
        )
        message = JSONRPCMessage(response)

        # Should handle exception gracefully
        transport._maybe_extract_protocol_version_from_message(message)
        assert transport.protocol_version is None

    @pytest.mark.anyio
    async def test_handle_sse_event_parsing_exception(self):
        """Test SSE event handling when message parsing fails."""
        transport = StreamableHTTPTransport("http://test.example.com")
        send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)

        async with send_stream, receive_stream:
            # Create invalid SSE event with malformed JSON
            sse = ServerSentEvent(event="message", data="invalid json{{{", id="1")

            result = await transport._handle_sse_event(sse, send_stream)

            # Should return False (not complete)
            assert result is False

            # Should have sent exception to stream
            exception = await receive_stream.receive()
            assert isinstance(exception, Exception)

    @pytest.mark.anyio
    async def test_handle_sse_event_unknown_event_type(self):
        """Test SSE event handling with unknown event type."""
        transport = StreamableHTTPTransport("http://test.example.com")
        send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)

        async with send_stream, receive_stream:
            # Create SSE event with unknown type
            sse = ServerSentEvent(event="unknown_event", data="some data", id="1")

            result = await transport._handle_sse_event(sse, send_stream)

            # Should return False and log warning
            assert result is False

    @pytest.mark.anyio
    async def test_handle_get_stream_no_session_id(self):
        """Test GET stream returns early when no session ID."""
        transport = StreamableHTTPTransport("http://test.example.com")
        send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)

        async with send_stream, receive_stream:
            # Ensure no session ID
            transport.session_id = None

            async with httpx.AsyncClient() as client:
                # Should return immediately without making request
                await transport.handle_get_stream(client, send_stream)

            # No messages should be sent
            with anyio.fail_after(0.1):
                with pytest.raises(anyio.WouldBlock):
                    receive_stream.receive_nowait()

    @pytest.mark.anyio
    async def test_handle_get_stream_connection_error(self):
        """Test GET stream handles connection errors gracefully."""
        transport = StreamableHTTPTransport("http://test.example.com")
        transport.session_id = "test-session-id"
        send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)

        async with send_stream, receive_stream:
            # Use invalid URL to trigger connection error
            transport.url = "http://invalid.local.test:99999/mcp"

            async with httpx.AsyncClient() as client:
                # Should handle exception without crashing
                await transport.handle_get_stream(client, send_stream)

            # No messages should be sent (error is logged but not raised)
            with anyio.fail_after(0.1):
                with pytest.raises(anyio.WouldBlock):
                    receive_stream.receive_nowait()

    @pytest.mark.anyio
    async def test_handle_resumption_request_without_token(self):
        """Test resumption request raises error without token."""
        transport = StreamableHTTPTransport("http://test.example.com")
        send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)

        async with send_stream, receive_stream:
            # Create request context without resumption token
            message = JSONRPCMessage(JSONRPCRequest(jsonrpc="2.0", method="test", id="1"))
            session_message = SessionMessage(message)

            async with httpx.AsyncClient() as client:
                from mcp.client.streamable_http import RequestContext

                ctx = RequestContext(
                    client=client,
                    headers={},
                    extensions=None,
                    session_id=None,
                    session_message=session_message,
                    metadata=ClientMessageMetadata(),  # No resumption token
                    read_stream_writer=send_stream,
                    sse_read_timeout=60,
                )

                with pytest.raises(ResumptionError, match="Resumption request requires a resumption token"):
                    await transport._handle_resumption_request(ctx)

    @pytest.mark.anyio
    async def test_handle_post_request_404_with_notification(self):
        """Test 404 response with notification (no error sent)."""
        transport = StreamableHTTPTransport("http://test.example.com")
        send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)

        async with send_stream, receive_stream:
            # Create a notification message
            message = JSONRPCMessage(
                JSONRPCNotification(
                    jsonrpc="2.0",
                    method="notifications/initialized",
                )
            )
            session_message = SessionMessage(message)

            # Mock client that returns 404
            mock_response = Mock()
            mock_response.status_code = 404
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_client = AsyncMock()
            mock_client.stream = Mock(return_value=mock_response)

            from mcp.client.streamable_http import RequestContext

            ctx = RequestContext(
                client=mock_client,
                headers={},
                extensions=None,
                session_id=None,
                session_message=session_message,
                metadata=None,
                read_stream_writer=send_stream,
                sse_read_timeout=60,
            )

            await transport._handle_post_request(ctx)

            # Should not send error for notifications (per MCP spec)
            with anyio.fail_after(0.1):
                with pytest.raises(anyio.WouldBlock):
                    receive_stream.receive_nowait()

    @pytest.mark.anyio
    async def test_handle_post_request_404_with_request(self):
        """Test 404 response with request sends session terminated error."""
        transport = StreamableHTTPTransport("http://test.example.com")
        send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)

        async with send_stream, receive_stream:
            # Create a request message
            message = JSONRPCMessage(JSONRPCRequest(jsonrpc="2.0", method="test", id="test-123"))
            session_message = SessionMessage(message)

            # Mock client that returns 404
            mock_response = Mock()
            mock_response.status_code = 404
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_client = AsyncMock()
            mock_client.stream = Mock(return_value=mock_response)

            from mcp.client.streamable_http import RequestContext

            ctx = RequestContext(
                client=mock_client,
                headers={},
                extensions=None,
                session_id=None,
                session_message=session_message,
                metadata=None,
                read_stream_writer=send_stream,
                sse_read_timeout=60,
            )

            await transport._handle_post_request(ctx)

            # Should send session terminated error
            error_message = await receive_stream.receive()
            assert isinstance(error_message, SessionMessage)
            assert isinstance(error_message.message.root, JSONRPCError)
            assert error_message.message.root.error.code == 32600
            assert "Session terminated" in error_message.message.root.error.message

    @pytest.mark.anyio
    async def test_handle_unexpected_content_type(self):
        """Test handling of unexpected content type."""
        transport = StreamableHTTPTransport("http://test.example.com")
        send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)

        async with send_stream, receive_stream:
            await transport._handle_unexpected_content_type("text/html", send_stream)

            # Should send ValueError
            error = await receive_stream.receive()
            assert isinstance(error, ValueError)
            assert "Unexpected content type: text/html" in str(error)

    @pytest.mark.anyio
    async def test_handle_json_response_parsing_error(self):
        """Test JSON response handling with parsing error."""
        transport = StreamableHTTPTransport("http://test.example.com")
        send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)

        async with send_stream, receive_stream:
            # Mock response with invalid JSON
            mock_response = Mock()
            mock_response.aread = AsyncMock(return_value=b"invalid json{{{")

            await transport._handle_json_response(mock_response, send_stream)

            # Should send exception
            error = await receive_stream.receive()
            assert isinstance(error, Exception)

    @pytest.mark.anyio
    async def test_handle_sse_response_error(self):
        """Test SSE response handling with error during iteration."""
        transport = StreamableHTTPTransport("http://test.example.com")
        send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)

        async with send_stream, receive_stream:
            message = JSONRPCMessage(JSONRPCRequest(jsonrpc="2.0", method="test", id="1"))
            session_message = SessionMessage(message)

            # Mock response that raises error during SSE iteration
            mock_response = Mock()
            mock_response.aclose = AsyncMock()

            from mcp.client.streamable_http import RequestContext

            ctx = RequestContext(
                client=Mock(),
                headers={},
                extensions=None,
                session_id=None,
                session_message=session_message,
                metadata=None,
                read_stream_writer=send_stream,
                sse_read_timeout=60,
            )

            # Mock EventSource that raises exception
            with patch("mcp.client.streamable_http.EventSource") as mock_event_source:
                mock_source_instance = Mock()

                async def error_iter():
                    raise RuntimeError("SSE iteration error")
                    yield  # pragma: no cover

                mock_source_instance.aiter_sse = Mock(return_value=error_iter())
                mock_event_source.return_value = mock_source_instance

                await transport._handle_sse_response(mock_response, ctx)

            # Should send exception
            error = await receive_stream.receive()
            assert isinstance(error, RuntimeError)
            assert "SSE iteration error" in str(error)

    @pytest.mark.anyio
    async def test_terminate_session_no_session_id(self):
        """Test session termination when no session ID exists."""
        transport = StreamableHTTPTransport("http://test.example.com")
        transport.session_id = None

        async with httpx.AsyncClient() as client:
            # Should return immediately without making request
            await transport.terminate_session(client)

        # No assertion needed - just verifying it doesn't crash

    @pytest.mark.anyio
    async def test_terminate_session_405_method_not_allowed(self):
        """Test session termination with 405 response."""
        transport = StreamableHTTPTransport("http://test.example.com")
        transport.session_id = "test-session"

        # Mock client that returns 405
        mock_response = Mock()
        mock_response.status_code = 405

        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value=mock_response)

        # Should log debug message but not raise
        await transport.terminate_session(mock_client)

    @pytest.mark.anyio
    async def test_terminate_session_non_success_status(self):
        """Test session termination with non-200/204 response."""
        transport = StreamableHTTPTransport("http://test.example.com")
        transport.session_id = "test-session"

        # Mock client that returns 500
        mock_response = Mock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(return_value=mock_response)

        # Should log warning but not raise
        await transport.terminate_session(mock_client)

    @pytest.mark.anyio
    async def test_terminate_session_connection_error(self):
        """Test session termination with connection error."""
        transport = StreamableHTTPTransport("http://test.example.com")
        transport.session_id = "test-session"

        # Mock client that raises exception
        mock_client = AsyncMock()
        mock_client.delete = AsyncMock(side_effect=httpx.ConnectError("Connection failed"))

        # Should log warning but not raise
        await transport.terminate_session(mock_client)

    @pytest.mark.anyio
    async def test_post_writer_exception_handling(self):
        """Test post_writer handles exceptions gracefully."""
        transport = StreamableHTTPTransport("http://test.example.com")

        write_stream, write_stream_reader = anyio.create_memory_object_stream[SessionMessage](10)
        read_send, read_receive = anyio.create_memory_object_stream[SessionMessage | Exception](10)
        write_stream_out, write_out_receive = anyio.create_memory_object_stream[SessionMessage](10)

        async with read_receive, write_out_receive:
            # Mock client that raises exception
            mock_client = AsyncMock()
            mock_client.stream = Mock(side_effect=RuntimeError("Connection error"))

            # Mock task group
            mock_tg = Mock()
            mock_tg.start_soon = Mock()

            def start_get_stream():
                pass

            # Send a message that will trigger the error
            message = JSONRPCMessage(JSONRPCNotification(jsonrpc="2.0", method="test"))
            await write_stream.send(SessionMessage(message))
            await write_stream.aclose()

            # Should handle exception and close streams (post_writer closes them)
            await transport.post_writer(
                mock_client, write_stream_reader, read_send, write_stream_out, start_get_stream, mock_tg
            )

    @pytest.mark.anyio
    async def test_handle_post_request_unexpected_content_type(self):
        """Test POST request with unexpected content type in response."""
        transport = StreamableHTTPTransport("http://test.example.com")
        send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)

        async with send_stream, receive_stream:
            # Create a request message
            message = JSONRPCMessage(JSONRPCRequest(jsonrpc="2.0", method="test", id="1"))
            session_message = SessionMessage(message)

            # Mock response with unexpected content type
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.raise_for_status = Mock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_client = AsyncMock()
            mock_client.stream = Mock(return_value=mock_response)

            from mcp.client.streamable_http import RequestContext

            ctx = RequestContext(
                client=mock_client,
                headers={},
                extensions=None,
                session_id=None,
                session_message=session_message,
                metadata=None,
                read_stream_writer=send_stream,
                sse_read_timeout=60,
            )

            await transport._handle_post_request(ctx)

            # Should send ValueError for unexpected content type
            error = await receive_stream.receive()
            assert isinstance(error, ValueError)
            assert "Unexpected content type" in str(error)

    @pytest.mark.anyio
    async def test_handle_post_request_202_accepted(self):
        """Test POST request with 202 Accepted response."""
        transport = StreamableHTTPTransport("http://test.example.com")
        send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)

        async with send_stream, receive_stream:
            # Create a notification message
            message = JSONRPCMessage(JSONRPCNotification(jsonrpc="2.0", method="test"))
            session_message = SessionMessage(message)

            # Mock response with 202 status
            mock_response = Mock()
            mock_response.status_code = 202
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_client = AsyncMock()
            mock_client.stream = Mock(return_value=mock_response)

            from mcp.client.streamable_http import RequestContext

            ctx = RequestContext(
                client=mock_client,
                headers={},
                extensions=None,
                session_id=None,
                session_message=session_message,
                metadata=None,
                read_stream_writer=send_stream,
                sse_read_timeout=60,
            )

            await transport._handle_post_request(ctx)

            # Should return early, no messages sent
            with anyio.fail_after(0.1):
                with pytest.raises(anyio.WouldBlock):
                    receive_stream.receive_nowait()


class TestStreamableHTTPResumption:
    """Test resumption-related edge cases."""

    @pytest.mark.anyio
    async def test_handle_resumption_request_extracts_original_id(self):
        """Test that resumption request extracts original request ID."""
        transport = StreamableHTTPTransport("http://test.example.com")
        send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)

        async with send_stream, receive_stream:
            # Create request with ID
            message = JSONRPCMessage(JSONRPCRequest(jsonrpc="2.0", method="test", id="original-id"))
            session_message = SessionMessage(message)

            # Mock successful SSE response
            mock_response = Mock()
            mock_response.raise_for_status = Mock()
            mock_response.aclose = AsyncMock()

            # Mock SSE that returns a response
            response_data = {
                "jsonrpc": "2.0",
                "id": "replaced-id",
                "result": {"success": True},
            }
            mock_sse = ServerSentEvent(event="message", data=json.dumps(response_data), id="1")

            async def mock_iter():
                yield mock_sse

            mock_event_source = Mock()
            mock_event_source.response = mock_response
            mock_event_source.aiter_sse = Mock(return_value=mock_iter())
            mock_event_source.__aenter__ = AsyncMock(return_value=mock_event_source)
            mock_event_source.__aexit__ = AsyncMock()

            mock_client = AsyncMock()

            from mcp.client.streamable_http import RequestContext

            token_updates: list[str] = []

            async def on_token_update(token: str):
                token_updates.append(token)

            metadata = ClientMessageMetadata(
                resumption_token="test-token",
                on_resumption_token_update=on_token_update,
            )

            ctx = RequestContext(
                client=mock_client,
                headers={},
                extensions=None,
                session_id=None,
                session_message=session_message,
                metadata=metadata,
                read_stream_writer=send_stream,
                sse_read_timeout=60,
            )

            with patch("mcp.client.streamable_http.aconnect_sse", return_value=mock_event_source):
                await transport._handle_resumption_request(ctx)

            # Token should have been updated
            assert "1" in token_updates


class TestStreamableHTTPInitialization:
    """Test initialization-related edge cases."""

    @pytest.mark.anyio
    async def test_protocol_version_extraction_from_sse_response(self):
        """Test protocol version is extracted from SSE initialization response."""
        transport = StreamableHTTPTransport("http://test.example.com")
        send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)

        async with send_stream, receive_stream:
            # Create initialization response
            init_result = {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "test", "version": "1.0"},
                "capabilities": {},
            }
            response_data = {
                "jsonrpc": "2.0",
                "id": "init-1",
                "result": init_result,
            }

            sse = ServerSentEvent(event="message", data=json.dumps(response_data), id="1")

            # Handle with initialization flag
            result = await transport._handle_sse_event(
                sse,
                send_stream,
                is_initialization=True,
            )

            # Should extract protocol version
            assert transport.protocol_version == "2025-03-26"
            assert result is True  # Response complete

    @pytest.mark.anyio
    async def test_protocol_version_extraction_from_json_response(self):
        """Test protocol version is extracted from JSON initialization response."""
        transport = StreamableHTTPTransport("http://test.example.com")
        send_stream, receive_stream = anyio.create_memory_object_stream[SessionMessage | Exception](10)

        async with send_stream, receive_stream:
            # Create mock JSON response
            init_result = {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "test", "version": "1.0"},
                "capabilities": {},
            }
            response_data = {
                "jsonrpc": "2.0",
                "id": "init-1",
                "result": init_result,
            }

            mock_response = Mock()
            mock_response.aread = AsyncMock(return_value=json.dumps(response_data).encode())

            await transport._handle_json_response(mock_response, send_stream, is_initialization=True)

            # Should extract protocol version
            assert transport.protocol_version == "2025-03-26"
