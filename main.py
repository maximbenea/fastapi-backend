import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import base64, os, asyncio, hashlib, time, queue, json
from contextlib import asynccontextmanager

from tenacity import retry_unless_exception_type

from gemini_api import gemini_request
from functools import lru_cache
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
    return hashlib.md5(image_base64).hexdigest()

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





