"""Read-only catalog endpoints."""

from fastapi import APIRouter
from pydantic import BaseModel

from covered.api.deps import Conn
from covered.domain import CATEGORY_NAMES
from covered.services import employees
from covered.store.records import Employee

router = APIRouter(tags=["catalog"])


class CategoryOut(BaseModel):
    code: str
    name: str


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/categories")
def list_categories() -> list[CategoryOut]:
    return [CategoryOut(code=code, name=name) for code, name in CATEGORY_NAMES.items()]


@router.get("/employees")
def list_employees(conn: Conn) -> list[Employee]:
    return employees.list_employees(conn)
