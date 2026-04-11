"""
Domain layer — entities, enums, policies, and invariants.

This package is intentionally framework-free: no SQLAlchemy, no FastAPI,
no PyQt. It contains only pure Python dataclasses, stdlib types (uuid,
datetime, Decimal), enumerations, policy constants/functions, and domain
exceptions. Any module that imports from here must not introduce framework
dependencies into this layer.
"""
