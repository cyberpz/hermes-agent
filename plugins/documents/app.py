"""Documents plugin standalone dev server.

Run from the plugin dir:
    PYTHONPATH=. ./.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8765

Or import the router into your own app:
    from plugin_api import router
    app.include_router(router, prefix="/api/documents")
"""
from fastapi import FastAPI

from plugin_api import router

app = FastAPI(title="Hermes Documents Plugin", version="0.1.0")
app.include_router(router, prefix="/api/documents")
