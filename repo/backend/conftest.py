"""
Shared pytest fixtures for District Console test suite.

Provides:
  - test_engine:            In-memory SQLite async engine with all ORM tables created.
  - db_session:             AsyncSession from test_engine (auto-commits per test).
  - sample_password:        Valid password string (>= MIN_PASSWORD_LENGTH).
  - seeded_user_orm:        A UserORM row inserted into the test DB with a hashed password.
  - seeded_roles:           4 roles + 13 permissions + role_permission mappings.
  - seeded_school:          SchoolORM for FK references.
  - seeded_warehouse:       WarehouseORM linked to seeded_school.
  - seeded_location:        LocationORM linked to seeded_warehouse.
  - seeded_inventory_item:  InventoryItemORM (sku="TEST-001", unit_cost="9.99").
  - seeded_stock_balance:   StockBalanceORM (quantity=100, available, not frozen).
  - seeded_resource:        ResourceORM (status=DRAFT).

These fixtures are available to all tests under unit_tests/ and api_tests/.
The asyncio_mode = "auto" setting in pyproject.toml means all async fixtures
and tests run automatically without the @pytest.mark.asyncio decorator.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from district_console.application.auth_service import AuthService
from district_console.infrastructure.orm import (
    Base,
    InventoryItemORM,
    LocationORM,
    PermissionORM,
    ResourceORM,
    RoleORM,
    RolePermissionORM,
    SchoolORM,
    StockBalanceORM,
    UserORM,
    WarehouseORM,
)
from district_console.infrastructure.repositories import RoleRepository, UserRepository


@pytest.fixture
async def test_engine():
    """
    Create an in-memory SQLite async engine with all ORM tables.

    Uses WAL-off (not relevant for in-memory), foreign keys enabled.
    Disposed after the test.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        # Ensure FK enforcement for in-memory test DB
        await conn.execute(__import__("sqlalchemy").text("PRAGMA foreign_keys=ON"))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine) -> AsyncSession:
    """
    Yield an AsyncSession wrapping the test engine.

    Each test gets a fresh session. Changes are NOT committed automatically —
    the test or the fixture under test must flush/commit as needed.
    """
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
def sample_password() -> str:
    """A valid plaintext password (17 chars, > MIN_PASSWORD_LENGTH=12)."""
    return "SecurePassword1!"


@pytest.fixture
async def seeded_user_orm(db_session: AsyncSession, sample_password: str) -> UserORM:
    """
    Insert a UserORM row with a hashed password into the test DB.

    Returns the ORM object. The password is sample_password.
    """
    from district_console.infrastructure.repositories import UserRepository

    auth = AuthService(UserRepository(), RoleRepository())
    password_hash = auth.hash_password(sample_password)

    user_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    orm = UserORM(
        id=user_id,
        username="testuser",
        password_hash=password_hash,
        is_active=True,
        failed_attempts=0,
        locked_until=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(orm)
    await db_session.flush()
    return orm


@pytest.fixture
async def seeded_roles(db_session: AsyncSession) -> dict:
    """
    Seed 4 roles, permissions, and role_permission mappings.

    Returns a dict keyed by role type: ADMINISTRATOR, LIBRARIAN, REVIEWER, TEACHER.
    """
    now = datetime.utcnow().isoformat()

    # Create permissions
    permissions = [
        ("resources.view", "resources", "view"),
        ("resources.create", "resources", "create"),
        ("resources.edit", "resources", "edit"),
        ("resources.import", "resources", "import"),
        ("resources.submit_review", "resources", "submit_review"),
        ("resources.publish", "resources", "publish"),
        ("resources.classify", "resources", "classify"),
        ("inventory.view", "inventory", "view"),
        ("inventory.adjust", "inventory", "adjust"),
        ("inventory.freeze", "inventory", "freeze"),
        ("inventory.count", "inventory", "count"),
        ("inventory.relocate", "inventory", "relocate"),
        ("inventory.approve_count", "inventory", "approve_count"),
        ("admin.manage_config", "admin", "manage_config"),
        ("integrations.manage", "integrations", "manage"),
        ("updates.manage", "updates", "manage"),
    ]
    perm_map = {}
    for name, resource_name, action in permissions:
        p = PermissionORM(
            id=str(uuid.uuid4()),
            name=name,
            resource_name=resource_name,
            action=action,
        )
        db_session.add(p)
        perm_map[name] = p
    await db_session.flush()

    # Create roles
    role_data = {
        "ADMINISTRATOR": "Administrator",
        "LIBRARIAN": "Librarian",
        "REVIEWER": "Reviewer",
        "TEACHER": "Teacher",
    }
    role_map = {}
    for role_type, display_name in role_data.items():
        r = RoleORM(
            id=str(uuid.uuid4()),
            role_type=role_type,
            display_name=display_name,
        )
        db_session.add(r)
        role_map[role_type] = r
    await db_session.flush()

    # Role→permission mappings
    admin_perms = list(perm_map.keys())
    librarian_perms = [
        "resources.view", "resources.create", "resources.edit", "resources.import",
        "resources.submit_review", "resources.classify",
        "inventory.view", "inventory.adjust", "inventory.freeze",
        "inventory.count", "inventory.relocate",
    ]
    reviewer_perms = [
        "resources.view", "resources.publish",
        "inventory.view",
    ]
    teacher_perms = ["resources.view", "inventory.view"]

    mapping = {
        "ADMINISTRATOR": admin_perms,
        "LIBRARIAN": librarian_perms,
        "REVIEWER": reviewer_perms,
        "TEACHER": teacher_perms,
    }
    for role_type, perm_names in mapping.items():
        role_orm = role_map[role_type]
        for perm_name in perm_names:
            rp = RolePermissionORM(
                role_id=role_orm.id,
                permission_id=perm_map[perm_name].id,
            )
            db_session.add(rp)
    await db_session.flush()

    return role_map


@pytest.fixture
async def seeded_school(db_session: AsyncSession) -> SchoolORM:
    """Insert a SchoolORM row for FK references."""
    school = SchoolORM(
        id=str(uuid.uuid4()),
        name="Test School",
        district_code="DIST-001",
        is_active=True,
    )
    db_session.add(school)
    await db_session.flush()
    return school


@pytest.fixture
async def seeded_warehouse(db_session: AsyncSession, seeded_school: SchoolORM) -> WarehouseORM:
    """Insert a WarehouseORM linked to seeded_school."""
    warehouse = WarehouseORM(
        id=str(uuid.uuid4()),
        name="Main Warehouse",
        school_id=seeded_school.id,
        address="123 Test St",
        is_active=True,
    )
    db_session.add(warehouse)
    await db_session.flush()
    return warehouse


@pytest.fixture
async def seeded_location(db_session: AsyncSession, seeded_warehouse: WarehouseORM) -> LocationORM:
    """Insert a LocationORM linked to seeded_warehouse."""
    location = LocationORM(
        id=str(uuid.uuid4()),
        warehouse_id=seeded_warehouse.id,
        zone="A",
        aisle="01",
        bin_label="A-01-01",
        is_active=True,
    )
    db_session.add(location)
    await db_session.flush()
    return location


@pytest.fixture
async def seeded_inventory_item(
    db_session: AsyncSession, seeded_user_orm: UserORM
) -> InventoryItemORM:
    """Insert an InventoryItemORM (sku='TEST-001', unit_cost='9.99')."""
    item = InventoryItemORM(
        id=str(uuid.uuid4()),
        sku="TEST-001",
        name="Test Item",
        description="A test inventory item",
        unit_cost="9.99",
        created_by=seeded_user_orm.id,
        created_at=datetime.utcnow().isoformat(),
    )
    db_session.add(item)
    await db_session.flush()
    return item


@pytest.fixture
async def seeded_stock_balance(
    db_session: AsyncSession,
    seeded_inventory_item: InventoryItemORM,
    seeded_location: LocationORM,
) -> StockBalanceORM:
    """Insert a StockBalanceORM (quantity=100, AVAILABLE, not frozen)."""
    balance = StockBalanceORM(
        id=str(uuid.uuid4()),
        item_id=seeded_inventory_item.id,
        location_id=seeded_location.id,
        batch_id=None,
        serial_id=None,
        status="AVAILABLE",
        quantity=100,
        is_frozen=False,
        freeze_reason=None,
        frozen_by=None,
        frozen_at=None,
    )
    db_session.add(balance)
    await db_session.flush()
    return balance


@pytest.fixture
async def seeded_resource(
    db_session: AsyncSession, seeded_user_orm: UserORM
) -> ResourceORM:
    """Insert a ResourceORM (status=DRAFT)."""
    fingerprint = hashlib.sha256(b"test content").hexdigest()
    dedup_key = hashlib.sha256(fingerprint.encode()).hexdigest()
    now = datetime.utcnow().isoformat()
    resource = ResourceORM(
        id=str(uuid.uuid4()),
        title="Test Resource",
        resource_type="BOOK",
        status="DRAFT",
        file_fingerprint=fingerprint,
        isbn="978-0-000000-00-0",
        dedup_key=dedup_key,
        created_by=seeded_user_orm.id,
        created_at=now,
        updated_at=now,
    )
    db_session.add(resource)
    await db_session.flush()
    return resource
