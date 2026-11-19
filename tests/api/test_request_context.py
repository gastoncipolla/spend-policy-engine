"""Request id and catch-all error handler (SPEC §12b)."""

import json
import logging
import re

import pytest
from api_builders import API_POLICY_TEXT

from covered.services.events import request_id_var


def _events(caplog) -> list[dict]:
    return [json.loads(record.getMessage()) for record in caplog.records]


def test_a_request_id_is_generated_when_none_is_sent(client):
    first = client.get("/categories").headers["X-Request-ID"]
    second = client.get("/categories").headers["X-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", first)
    assert first != second


def test_a_valid_incoming_request_id_is_kept(client):
    response = client.get("/categories", headers={"X-Request-ID": "abc-123.x_Y:9"})
    assert response.headers["X-Request-ID"] == "abc-123.x_Y:9"


@pytest.mark.parametrize(
    "bad", ["", "has space", "a" * 129, "new\\nline", "ñ".encode()]
)
def test_an_invalid_incoming_request_id_is_replaced(client, bad):
    response = client.get("/categories", headers={"X-Request-ID": bad})
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


def test_error_responses_carry_the_request_id_too(client):
    response = client.get("/expenses/999", headers={"X-Request-ID": "req-404"})
    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "req-404"


def test_every_log_line_of_a_request_carries_its_id(client, caplog):
    policy = client.post("/policies", json={"name": "Sales"}).json()
    client.post(f"/policies/{policy['id']}/versions", json={"text": API_POLICY_TEXT})
    with caplog.at_level(logging.INFO, logger="covered"):
        client.post(
            f"/policies/{policy['id']}/versions/1/compile",
            headers={"X-Request-ID": "req-compile"},
        )
    events = _events(caplog)
    assert [e["event"] for e in events] == ["policy_compiled"]
    assert {e["request_id"] for e in events} == {"req-compile"}
    assert request_id_var.get() is None  # not leaked outside the request


def test_unexpected_errors_are_a_500_envelope_and_logged_with_the_trace(client, caplog):
    def boom():
        raise RuntimeError("database on fire")

    client.app.add_api_route("/boom", boom)
    with caplog.at_level(logging.INFO, logger="covered"):
        response = client.get("/boom", headers={"X-Request-ID": "req-500"})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "req-500"
    body = response.json()
    assert body["error"] == "internal_error"
    assert body["request_id"] == "req-500"
    assert "fire" not in body["message"]  # internals stay in the log

    [record] = caplog.records
    assert record.levelno == logging.ERROR
    event = json.loads(record.getMessage())
    assert event["event"] == "unhandled_error"
    assert event["request_id"] == "req-500"
    assert (event["method"], event["path"]) == ("GET", "/boom")
    assert "RuntimeError: database on fire" in event["traceback"]
    assert "Traceback" in event["traceback"]
