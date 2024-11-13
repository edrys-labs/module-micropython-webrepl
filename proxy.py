import asyncio
import websockets
import logging
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('websocket_proxy')

async def forward(ws_from, ws_to, name="unknown"):
    try:
        async for message in ws_from:
            if isinstance(message, bytes):
                logger.debug(f"{name} forwarding binary message of length {len(message)}")
                if len(message) >= 2:
                    logger.debug(f"First two bytes: {message[:2].hex()}")
                await ws_to.send(message)
                await asyncio.sleep(0.01)  # Small delay after binary messages
            else:
                logger.debug(f"{name} forwarding text message: {message[:100]}")
                await ws_to.send(message)
    except websockets.ConnectionClosed as e:
        logger.info(f"Connection closed by {name}: {e.code} {e.reason}")
        # Ensure the other websocket is also closed
        if not ws_to.closed:
            await ws_to.close(1000, "Other end closed")
    except Exception as e:
        logger.error(f"Error in {name} forward: {str(e)}")
        if not ws_to.closed:
            await ws_to.close(1001, f"Error in forwarding: {str(e)}")

async def proxy(websocket, path):
    target_ws = None
    try:
        target_uri = path.lstrip('/')
        
        if not target_uri.startswith('ws://'):
            logger.error(f"Invalid target URI: {target_uri}")
            await websocket.close(1008, "Invalid target URI. Must start with ws://")
            return
            
        try:
            parsed = urlparse(target_uri)
            if not parsed.netloc:
                raise ValueError("Invalid URI format")
        except Exception as e:
            logger.error(f"URI parsing error: {str(e)}")
            await websocket.close(1008, "Invalid URI format")
            return

        logger.info(f"New connection from {websocket.remote_address} to {target_uri}")

        async with websockets.connect(
            target_uri,
            subprotocols=['binary', 'base64'],
            max_size=None,
            ping_interval=None,
            ping_timeout=None,
            close_timeout=10,
            max_queue=2**16
        ) as target_ws:
            # Create forwarding tasks
            forward_tasks = [
                asyncio.create_task(forward(websocket, target_ws, f"client->{target_uri}")),
                asyncio.create_task(forward(target_ws, websocket, f"{target_uri}->client"))
            ]

            # Wait for any task to complete (which will happen when either connection closes)
            done, pending = await asyncio.wait(
                forward_tasks,
                return_when=asyncio.FIRST_COMPLETED
            )

            # Cancel pending tasks
            for task in pending:
                task.cancel()

            # Wait for cancellation to complete
            if pending:
                await asyncio.wait(pending)

            # Ensure both connections are closed
            if not websocket.closed:
                await websocket.close(1000, "Target connection closed")
            if not target_ws.closed:
                await target_ws.close(1000, "Client connection closed")

    except websockets.exceptions.WebSocketException as e:
        logger.error(f"WebSocket error: {str(e)}")
        if not websocket.closed:
            await websocket.close(1011, f"WebSocket error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        if not websocket.closed:
            await websocket.close(1011, f"Unexpected error: {str(e)}")
    finally:
        logger.info(f"Proxy connection closed for {websocket.remote_address}")

async def main():
    server = await websockets.serve(
        proxy,
        "localhost",
        8765,
        subprotocols=['binary', 'base64'],
        max_size=None,
        ping_interval=None,
        ping_timeout=None,
        close_timeout=10,
        max_queue=2**16
    )
    
    logger.info("Proxy server listening on ws://localhost:8765")
    logger.info("Connect using: ws://localhost:8765/ws://target-host:port")
    
    try:
        await server.wait_closed()
    except KeyboardInterrupt:
        logger.info("Shutting down proxy server...")
        server.close()
        await server.wait_closed()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Proxy server shutdown complete")