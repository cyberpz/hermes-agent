"""Library Plugin entrypoint."""
from .plugin_api import router

def register(app):
    app.include_router(router)
