"""CSRF guard on cookie-authenticated writes (src/covered/web/csrf.py)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from covered.web.csrf import CsrfMiddleware


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(CsrfMiddleware)

    @app.post("/write")
    def write():
        return {"ok": True}

    @app.get("/read")
    def read():
        return {"ok": True}

    return TestClient(app)


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_cross_site_browser_post_is_blocked(client, site):
    response = client.post("/write", headers={"Sec-Fetch-Site": site})
    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


@pytest.mark.parametrize("site", ["same-origin", "none"])
def test_same_origin_browser_post_is_allowed(client, site):
    assert client.post("/write", headers={"Sec-Fetch-Site": site}).status_code == 200


def test_foreign_origin_is_blocked_when_fetch_metadata_is_missing(client):
    assert (
        client.post("/write", headers={"Origin": "https://evil.example"}).status_code
        == 403
    )


def test_same_origin_header_is_allowed(client):
    assert (
        client.post("/write", headers={"Origin": "http://testserver"}).status_code
        == 200
    )


def test_bearer_api_calls_are_not_affected(client):
    headers = {"Authorization": "Bearer demo-ana", "Sec-Fetch-Site": "cross-site"}
    assert client.post("/write", headers=headers).status_code == 200


def test_reads_and_non_browser_clients_pass(client):
    assert (
        client.get("/read", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200
    )
    assert client.post("/write").status_code == 200
