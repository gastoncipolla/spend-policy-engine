"""`POST /expenses/parse`: auth, CSRF, limits, and nothing evaluated or stored."""

from api_builders import bearer

from covered.intake import MAX_TEXT_LENGTH, MockIntakeProvider


def use_mock(client):
    client.app.state.intake_provider = MockIntakeProvider()


def test_parse_returns_a_draft_and_stores_nothing(client):
    use_mock(client)
    response = client.post(
        "/expenses/parse",
        json={"text": "Uber to the airport yesterday USD 45"},
        headers=bearer("ana"),
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["draft"]["category"] == "ground_transport"
    assert body["draft"]["amount_minor"] == 4500
    assert (body["provider"], body["model"]) == ("mock", "mock")
    assert "outcome" not in body and "decision" not in body
    assert client.get("/expenses", headers=bearer("ana")).json() == []


def test_parse_requires_a_known_bearer_token(client):
    use_mock(client)
    anonymous = client.post(
        "/expenses/parse", json={"text": "taxi USD 20"}, headers={"Authorization": ""}
    )
    assert anonymous.status_code == 401
    unknown = client.post(
        "/expenses/parse",
        json={"text": "taxi USD 20"},
        headers={"Authorization": "Bearer nope"},
    )
    assert unknown.status_code == 401


def test_parse_rejects_long_or_extra_input(client):
    use_mock(client)
    too_long = client.post(
        "/expenses/parse", json={"text": "x" * (MAX_TEXT_LENGTH + 1)}
    )
    assert too_long.status_code == 422
    assert too_long.json()["error"] == "validation_error"
    extra = client.post(
        "/expenses/parse", json={"text": "taxi", "decision": "approved"}
    )
    assert extra.status_code == 422


def test_bearer_calls_are_not_blocked_by_csrf_but_cookie_ones_are(client):
    use_mock(client)
    cross_site = {"Sec-Fetch-Site": "cross-site"}
    with_bearer = client.post(
        "/expenses/parse", json={"text": "taxi USD 20"}, headers=cross_site
    )
    assert with_bearer.status_code == 200
    client.cookies.set("covered_token", "demo-ana")
    with_cookie = client.post(
        "/expenses/parse",
        json={"text": "taxi USD 20"},
        headers={**cross_site, "Authorization": ""},
    )
    assert with_cookie.status_code == 403
