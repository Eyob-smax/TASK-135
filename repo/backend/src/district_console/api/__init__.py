"""
Local REST API layer.

FastAPI application and routers, Pydantic request/response schemas, HMAC
signature verification middleware, rate-limit middleware, and error envelope
formatting. All endpoints are bound to 127.0.0.1:8765 and are local-only —
no internet exposure. Route handlers delegate to application-layer services
and never contain persistence logic directly.
"""
