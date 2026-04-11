"""
Application layer — use-case orchestration services.

Each service class coordinates one domain workflow (e.g. AuthService,
ResourceService, InventoryService). Services depend on repository interfaces
defined in the infrastructure layer, emit domain events, and enforce
cross-cutting rules such as RBAC scope checks and checkpoint recording.
No SQLAlchemy sessions or PyQt widgets belong here.
"""
