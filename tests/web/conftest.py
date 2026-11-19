"""The pages on a seeded demo database, compiled with the mock provider."""

import pytest
from fastapi.testclient import TestClient

from covered.api import create_app
from covered.compiler import MockProvider
from covered.services.provider_compiler import ProviderCompiler
from covered.services.seed import reset_database, seed


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "web.db")
    conn = reset_database(db_path)
    seed(conn)
    conn.close()
    app = create_app(db_path, compiler=ProviderCompiler(MockProvider()))
    with TestClient(app) as test_client:
        yield test_client
