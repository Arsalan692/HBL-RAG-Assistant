"""The HTTP surface: SSE chat, the document library, health.

Not imported here. `create_app` pulls in FastAPI, and the provider registry has
to be able to describe this backend from a machine where it is not installed.
"""
