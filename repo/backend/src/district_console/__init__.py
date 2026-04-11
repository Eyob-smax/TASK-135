"""
District Resource & Inventory Operations Console.

A fully offline Windows desktop application for K-12 organizations to manage
reading resources, physical inventory, and administrative operations.

Stack:
- Desktop UI: PyQt6
- Local REST service: FastAPI on 127.0.0.1:8765
- Persistence: SQLite (WAL mode) via SQLAlchemy 2.x + Alembic
- Password hashing: Argon2id (argon2-cffi)
- Background scheduling: APScheduler 3.x
"""
