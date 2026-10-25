"""ASGI entry point: ``uvicorn services.api.main:app``."""

from services.api.app import create_app

app = create_app()
