"""A seeded demo database (SPEC §9) and an app on it with the mock compiler."""

import pytest
from fastapi.testclient import TestClient

from covered.api import create_app
from covered.compiler import MockProvider
from covered.services.provider_compiler import ProviderCompiler
from covered.services.seed import reset_database, seed


@pytest.fixture
def seeded_db(tmp_path):
    db_path = str(tmp_path / "demo.db")
    conn = reset_database(db_path)
    seed(conn)
    conn.close()
    return db_path


@pytest.fixture
def client(seeded_db):
    """Calls as fede (finance) unless a test passes other headers."""
    app = create_app(seeded_db, compiler=ProviderCompiler(MockProvider()))
    with TestClient(app, headers={"Authorization": "Bearer demo-fede"}) as test_client:
        yield test_client
