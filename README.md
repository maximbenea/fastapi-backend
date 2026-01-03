#     fastapi-backend

This is the backend service for the **MoldSEF** project. It is built with **FastAPI** and provides the core logic, including AI integration via **Google Gemini**, caching, and real-time communication using WebSockets. It's purpose is to capture screenshots from frontend process via Gemini and predict a scent, which will be then sent both to the fronted for preview and to an ESP8266.

The backed itself is accesible via [https://fastapi-backend-i18f.onrender.com](https://fastapi-backend-i18f.onrender.com) a free hosting solution.

## Structure

*   **`main.py`**: The entry point of the application. Contains the API routes, WebSocket handlers, and server configuration.
*   **`gemini_api.py`**: A wrapper module for interacting with Google's Gemini AI models.

## Features I am proud of

*   **High Performance**: Built on [FastAPI](https://fastapi.tiangolo.com/), one of the fastest frameworks.
*   **AI Powered**: Integrated with Google Gemini.
*   **Real-time**: Supports WebSockets for live updates.
*   **Caching**: optimized response times (in-memory caching).

