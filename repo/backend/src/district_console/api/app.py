"""
FastAPI application factory for the District Console local REST API.

The API is local-only (127.0.0.1:8765) and has no public documentation
endpoints. OpenAPI/Swagger/ReDoc are all disabled.

Usage:
    container = await bootstrap()
    app = create_app(container)
    # Start with uvicorn.run(app, host="127.0.0.1", port=8765) in a thread
"""
from __future__ import annotations

from fastapi import FastAPI

from district_console.api.middleware import ErrorHandlerMiddleware
from district_console.api.routers.auth import router as auth_router
from district_console.api.routers.resources import router as resources_router
from district_console.api.routers.inventory import router as inventory_router
from district_console.api.routers.count_sessions import router as count_sessions_router
from district_console.api.routers.relocations import router as relocations_router
from district_console.api.routers.integrations import router as integrations_router
from district_console.api.routers.integration_inbound import router as integration_inbound_router
from district_console.api.routers.admin.config import router as admin_config_router
from district_console.api.routers.admin.taxonomy import router as admin_taxonomy_router
from district_console.api.routers.admin.updates import router as admin_updates_router
from district_console.api.routers.admin.audit import router as admin_audit_router


def create_app(container: object) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        container: AppContainer instance with all services wired.
                   Stored as app.state.container so dependencies can access it.

    Returns:
        Configured FastAPI instance (not yet running).
    """
    app = FastAPI(
        title="District Console API",
        version="0.1.0",
        # Local-only service — no public docs
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    # Store the application container so dependencies can inject services
    app.state.container = container

    # Middleware (registered in reverse execution order — last added runs first)
    app.add_middleware(ErrorHandlerMiddleware)

    # Routers
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(resources_router, prefix="/api/v1/resources", tags=["resources"])
    app.include_router(inventory_router, prefix="/api/v1/inventory", tags=["inventory"])
    app.include_router(count_sessions_router, prefix="/api/v1/inventory", tags=["count-sessions"])
    app.include_router(relocations_router, prefix="/api/v1/inventory", tags=["relocations"])
    app.include_router(integrations_router, prefix="/api/v1/integrations", tags=["integrations"])
    app.include_router(integration_inbound_router, prefix="/api/v1/integrations/inbound", tags=["integration-inbound"])
    app.include_router(admin_config_router, prefix="/api/v1/admin/config", tags=["admin-config"])
    app.include_router(admin_taxonomy_router, prefix="/api/v1/admin/taxonomy", tags=["admin-taxonomy"])
    app.include_router(admin_updates_router, prefix="/api/v1/admin/updates", tags=["admin-updates"])
    app.include_router(admin_audit_router, prefix="/api/v1/admin/audit", tags=["admin-audit"])

    return app
