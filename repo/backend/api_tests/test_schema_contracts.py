"""
Scaffold tests for API schema contract validation.

At Prompt 2 stage, verifies that pydantic is correctly installed and that
base schema patterns (pagination envelope, standard response wrappers) are
definable and usable. Full route-level schema tests are added in Prompts 3–4.
"""
from __future__ import annotations

from typing import Any, Generic, List, Optional, TypeVar

import pytest
from pydantic import BaseModel, Field, ValidationError

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Common response schema patterns (will be extracted to api/schemas.py in Prompt 3)
# ---------------------------------------------------------------------------

class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    offset: int
    limit: int


class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPydanticAvailable:
    def test_pydantic_importable(self) -> None:
        import pydantic
        assert pydantic is not None

    def test_pydantic_version_2(self) -> None:
        import pydantic
        major = int(pydantic.__version__.split(".")[0])
        assert major >= 2, f"Pydantic v2+ required; found {pydantic.__version__}"


class TestPaginatedResponseSchema:
    def test_valid_paginated_response(self) -> None:
        class Item(BaseModel):
            id: str
            name: str

        response = PaginatedResponse[Item](
            items=[{"id": "1", "name": "A"}, {"id": "2", "name": "B"}],
            total=100,
            offset=0,
            limit=50,
        )
        assert response.total == 100
        assert len(response.items) == 2
        assert response.items[0].name == "A"

    def test_empty_items_valid(self) -> None:
        class Item(BaseModel):
            id: str

        response = PaginatedResponse[Item](items=[], total=0, offset=0, limit=50)
        assert response.items == []
        assert response.total == 0

    def test_missing_total_raises(self) -> None:
        class Item(BaseModel):
            id: str

        with pytest.raises(ValidationError):
            PaginatedResponse[Item](items=[], offset=0, limit=50)  # type: ignore[call-arg]


class TestHealthResponseSchema:
    def test_valid_health_response(self) -> None:
        resp = HealthResponse(status="ok")
        assert resp.status == "ok"
        assert resp.version == "0.1.0"

    def test_custom_version(self) -> None:
        resp = HealthResponse(status="ok", version="1.2.3")
        assert resp.version == "1.2.3"

    def test_missing_status_raises(self) -> None:
        with pytest.raises(ValidationError):
            HealthResponse()  # type: ignore[call-arg]


class TestBaseModelBehaviour:
    def test_model_extra_fields_forbidden(self) -> None:
        """Demonstrate strict schema usage pattern for API models."""
        class StrictModel(BaseModel):
            model_config = {"extra": "forbid"}
            name: str

        with pytest.raises(ValidationError):
            StrictModel(name="test", unexpected_field="oops")

    def test_model_serializes_to_json(self) -> None:
        class Sample(BaseModel):
            code: str
            value: int

        sample = Sample(code="ABC", value=42)
        json_str = sample.model_dump_json()
        assert '"code":"ABC"' in json_str or '"code": "ABC"' in json_str
