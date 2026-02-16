"""ZeroMQ IPC server — ROUTER for RPC, PUB for real-time events."""

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine, Optional

import zmq
import zmq.asyncio

from hw_controller.ipc.protocol import (
    JsonRpcError,
    error_response,
    event_message,
    parse_request,
    success_response,
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
)

logger = logging.getLogger(__name__)

# Type alias for RPC handlers: async (params: dict) -> Any
RpcHandler = Callable[[dict], Coroutine[Any, Any, Any]]


class IPCServer:
    """
    Async ZeroMQ server with two channels:

    - **RPC** (ROUTER ↔ DEALER): request/response for commands like
      ``camera.capture``, ``session.start``, etc.
    - **Events** (PUB → SUB): one-way broadcast for state changes,
      progress updates, and error notifications.
    """

    def __init__(self, rpc_port: int = 5555, pub_port: int = 5556):
        self._ctx = zmq.asyncio.Context()
        self._rpc_socket = self._ctx.socket(zmq.ROUTER)
        self._pub_socket = self._ctx.socket(zmq.PUB)
        self._rpc_port = rpc_port
        self._pub_port = pub_port
        self._handlers: dict[str, RpcHandler] = {}
        self._running = False

    async def start(self) -> None:
        """Bind both sockets and mark the server as running."""
        self._rpc_socket.bind(f"tcp://127.0.0.1:{self._rpc_port}")
        self._pub_socket.bind(f"tcp://127.0.0.1:{self._pub_port}")
        self._running = True
        logger.info(
            "IPC server listening — RPC:%d  PUB:%d",
            self._rpc_port, self._pub_port,
        )

    def register(self, method: str, handler: RpcHandler) -> None:
        """Register an async RPC handler for a method name.

        Example::

            server.register("camera.capture", camera_capture_handler)
        """
        self._handlers[method] = handler
        logger.debug("Registered RPC method: %s", method)

    async def run(self) -> None:
        """Main loop — receive and dispatch JSON-RPC requests."""
        await self.start()
        try:
            while self._running:
                try:
                    frames = await asyncio.wait_for(
                        self._rpc_socket.recv_multipart(), timeout=1.0
                    )
                    # ROUTER framing: [identity, delimiter, payload]
                    if len(frames) >= 3:
                        identity, _, raw = frames[0], frames[1], frames[2]
                        asyncio.create_task(self._handle_request(identity, raw))
                except asyncio.TimeoutError:
                    continue  # allows clean shutdown checks
        except asyncio.CancelledError:
            logger.info("IPC server loop cancelled")
        finally:
            await self.shutdown()

    async def _handle_request(self, identity: bytes, raw: bytes) -> None:
        """Parse, dispatch, and respond to a single RPC request."""
        req_id: Optional[str] = None
        try:
            msg = parse_request(raw)
            method = msg["method"]
            params = msg.get("params", {})
            req_id = msg.get("id")

            handler = self._handlers.get(method)
            if handler is None:
                resp = error_response(req_id, METHOD_NOT_FOUND, f"Unknown: {method}")
            else:
                result = await handler(params)
                resp = success_response(req_id, result)

        except JsonRpcError as e:
            resp = error_response(req_id, e.code, e.message, e.data)
        except Exception as e:
            logger.exception("Unhandled error in RPC handler")
            resp = error_response(req_id, INTERNAL_ERROR, str(e))

        payload = json.dumps(resp).encode()
        await self._rpc_socket.send_multipart([identity, b"", payload])

    async def publish_event(self, event_name: str, data: dict) -> None:
        """Broadcast a real-time event to all SUB clients.

        Args:
            event_name: Topic name (e.g. "state_changed", "error").
            data: Arbitrary dict payload.
        """
        msg = event_message(event_name, data)
        payload = json.dumps(msg).encode()
        await self._pub_socket.send_multipart([event_name.encode(), payload])

    async def shutdown(self) -> None:
        """Gracefully close sockets and terminate the ZMQ context."""
        self._running = False
        self._rpc_socket.close(linger=0)
        self._pub_socket.close(linger=0)
        self._ctx.term()
        logger.info("IPC server shut down")
