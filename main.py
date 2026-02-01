import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import base64, os, asyncio, hashlib, time, queue, json
from contextlib import asynccontextmanager

from gemini_api import gemini_request
from groq_api import groq_request
from concurrent.futures import ThreadPoolExecutor
import threading
from typing import List

class Image(BaseModel):
    image_base64: str

# Global state
# When the frontend uploads an image, it's put here, following the FIFO principle
processing_queue = queue.Queue()
broadcast_queue = queue.Queue()     # Queue for websocket broadcast to all clients
current_scent_result = ""

active_workers = 0
MAX_WORKERS = 3                     # Processing only up to 3 images simultaneously

# Simple in-memory cache for scent results
scent_cache = {}
CACHE_TTL = 300     # Cache will be alive for 300s
CACHE_MAX_SIZE = 100

# Thread pool for Gemini processing
# Role: pre-create a pool of MAX_WORKERS ready to execute tasks (e.g. processing image)
# *See more in documentation
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# Standard manager for Websockets
class ConnectionManager:
    def __init__(self):
        # Handling active connections via two different lists because in makes implementing different
        # messages for different types of clients easier (if needed)
        self.active_connections: List[WebSocket] = []
        self.esp8266_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket, client_type: str = "web"):    # Make the "web" default client type
        await websocket.accept()
        if client_type == "esp8266":
            self.esp8266_connections.append(websocket)
            print(f"esp8266 connected. Total esp8266 connections: {len(self.esp8266_connections)}")
        else:
            self.active_connections.append(websocket)
            print(f"web client connected to websocket. Total web connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket, client_type: str = "web"):
        if client_type == "esp8266":
            if websocket in self.esp8266_connections:
                self.esp8266_connections.remove(websocket)
            print(f"esp8266 disconnected. Total esp8266 connections: {len(self.esp8266_connections)}")
        else:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
            print(f"web client disconnected. Total web connections: {len(self.active_connections)}")

    async def broadcast_to_esp8266(self, message: str):
        # If there are active esp8266 connections
        if self.esp8266_connections:
            # Gracefully handle the disconnections of clients while sending data
            disconnected = []
            for connection in self.esp8266_connections:
                # Crucial to use try and expect
                try:
                    await connection.send_text(message)
                    print(f"message sent to esp8266 successfully")
                except Exception as e:
                    print(f"failed to send to esp8266: {e}")
                    # Here the problematic connection is handled so it does not cause any problems in future
                    disconnected.append(connection)

            # Remove those disconnected clients
            for connection in disconnected:
                self.esp8266_connections.remove(connection)
        else:
            print("no esp connections available to broadcast")

    # Similar to esp broadcast logic but for the web client
    async def broadcast_to_web(self, message: str):
        if self.active_connections:
            disconnected = []
            for connection in self.active_connections:
                try:
                    await connection.send_text(message)
                    print(f"message sent to web client successfully")
                except Exception as e:
                    print(f"failed to send to web: {e}")
                    disconnected.append(connection)

            for connection in disconnected:
                self.active_connections.remove(connection)

        # Impossible case in this specific application
        else:
            print("no web connections available to broadcast")

manager = ConnectionManager()   # Finished with websocket implementation

# Caching functions
def get_image_hash(image_base64):
    """ Creates a hash from the base64 encoded image, used in further caching"""
    # Since the MD5 operates only on binary data the base64 image will go through following steps:
    # Base64 -> Binary -> Binary Hash -> Hexadecimal Hash
    return hashlib.md5(image_base64.encode()).hexdigest()

def get_cached_result(image_hash):
    """Verify whether the image has already been cached in memory"""
    if image_hash in scent_cache:
        # Key-value representation where the value is an array of 2 elements
        result, timestamp = scent_cache[image_hash]
        # Check the data 'freshness'
        if time.time() - timestamp < CACHE_TTL:
            return result
        else:
            # Remove expired entry
            del scent_cache[image_hash]
    return None

def cache_results(image_hash, result):
    """Cache the result"""
    if len(scent_cache) > CACHE_MAX_SIZE:
        # Find the key in the cache that has the smallest timestamp
        # Using the lambda comparator for the min function, it looks at all timestamps for each key
        oldest_key = min(scent_cache.keys(), key=lambda k: scent_cache[k][1])
        del scent_cache[oldest_key]

    scent_cache[image_hash] = (result, time.time())

# Core logic
def process_image_worker(image_base64):
    """Worker function that processes a single image"""
    global current_scent_result, active_workers

    try:
        # First check the cache
        image_hash = get_image_hash(image_base64)
        cached_result = get_cached_result(image_hash)

        if cached_result:
            print(f"cache hit for {image_hash[:8]}")
            current_scent_result = cached_result
        else:
            print(f"cache miss for {image_hash[:8]}, processing image")
            # ! Could arise conflict between workers, because they use the same path
            file_path = "image.jpg"

            # Create the image for the gemini api
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(image_base64[23:]))

            result = groq_request()
            cache_results(image_hash, result)
            current_scent_result = result
            print(f"gemini result: {result}")

            os.remove(file_path)

        # Queue the message for the main loop to handle, so that the workers don't interact with asyncio function
        if current_scent_result:
            clean_result = current_scent_result.strip('"').strip("'")
            # Serialize the cleaned python string into a JSON string
            message = json.dumps({"message": clean_result})
            broadcast_queue.put(message)
            print(f"queued broadcast message: {message}")

    except Exception as e:
        print(f"error processing image: {e}")
    finally:
        active_workers -= 1

# Background loop
async def processing_loop():
    global active_workers

    while True:
        if not processing_queue.empty() and MAX_WORKERS > active_workers:
            image_base64 = processing_queue.get()
            active_workers += 1

            # Submit to the thread pool
            executor.submit(process_image_worker, image_base64)
            print(f"processing image, active workers: {active_workers}")

        if not broadcast_queue.empty():
            message = broadcast_queue.get()
            print(f"processing broadcast message: {message}")

            await manager.broadcast_to_esp8266(message)
            await manager.broadcast_to_web(message)

        # A very important pause for HTTP requests
        await asyncio.sleep(0.1)

# Manage startup and shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background loop
    task = asyncio.create_task(processing_loop())
    yield
    # Stop loop on shutdown
    task.cancel()

    # Handling clean shutdown
    try:
        await task
    except asyncio.CancelledError:
        pass

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],    # Should be later changed to actual fronted origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mostly for development debugging, will not be used in actual app
@app.get("/processing")
async def get_processing_state():
    return {
        "processing": active_workers > 0,
        "active_workers": active_workers,
        "max_workers": MAX_WORKERS,
        "queue_size": processing_queue.qsize()
    }

@app.get("/cache_stats")
async def get_cache_stats():
    return {
        "cache_size": len(scent_cache),
        "max_cache_size": CACHE_MAX_SIZE,
        "cache_ttl": CACHE_TTL
    }

@app.post("/test-broadcast")
async def test_broadcast():
    """Test endpoint to manually trigger a broadcast to all clients"""
    test_message = json.dumps({"message": "test_scent"})
    await manager.broadcast_to_esp8266(test_message)
    await manager.broadcast_to_web(test_message)
    return {
        "status": "broadcast_sent",
        "message": test_message,
        "esp8266_connections": len(manager.esp8266_connections),
        "web_connections": len(manager.active_connections)
    }

# Actual used API endpoints
@app.post("/upload-frame")
async def upload_image(image: Image):
    # Add to processing queue
    processing_queue.put(image.image_base64)
    return {
        "status": "queued",
        "queue_position": processing_queue.qsize(),
        "active_workers": active_workers
    }

@app.websocket("/ws/web")
async def websocket_web_endpoint(websocket: WebSocket):
    await manager.connect(websocket, "web")
    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, "web")

@app.websocket("/ws/esp8266")
async def websocket_esp8266_endpoint(websocket: WebSocket):
    await manager.connect(websocket, "esp8266")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, "esp8266")

