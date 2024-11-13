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
                    
                # Add small delay after binary messages to prevent buffer overrun
                await ws_to.send(message)
                await asyncio.sleep(0.01)  # 10ms delay
            else:
                logger.debug(f"{name} forwarding text message: {message[:100]}")
                await ws_to.send(message)
    except websockets.ConnectionClosed as e:
        logger.info(f"Connection closed by {name}: {e.code} {e.reason}")
    except Exception as e:
        logger.error(f"Error in {name} forward: {str(e)}")
        # Don't re-raise the exception to keep the other direction running

async def proxy(websocket, path):
    target_uri = None
    try:
        # Remove leading slash and parse target URI
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

        # Configure WebSocket connection with more lenient timeouts
        async with websockets.connect(
            target_uri,
            subprotocols=['binary', 'base64'],
            max_size=None,
            ping_interval=None,  # Disable automatic ping
            ping_timeout=None,   # Disable ping timeout
            close_timeout=10,    # More time for clean shutdown
            max_queue=2**16      # Larger message queue
        ) as target_ws:
            # Create bidirectional forwarding tasks
            forward_tasks = [
                asyncio.create_task(forward(websocket, target_ws, f"client->{target_uri}")),
                asyncio.create_task(forward(target_ws, websocket, f"{target_uri}->client"))
            ]

            # Wait for both tasks to complete (or one to fail)
            try:
                await asyncio.gather(*forward_tasks)
            except Exception as e:
                logger.error(f"Error in forwarding: {str(e)}")
            finally:
                # Ensure all tasks are cleaned up
                for task in forward_tasks:
                    if not task.done():
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

    except websockets.exceptions.WebSocketException as e:
        logger.error(f"WebSocket error for {target_uri}: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
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