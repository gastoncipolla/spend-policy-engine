"""The "Ask Covered" box on the employee page (POST /employee/interpret)."""

from covered.intake import MockIntakeProvider


def act_as(client, user_id):
    return client.post("/act-as", data={"user_id": user_id, "next": "/employee"})


def interpret(client, text, **headers):
    client.app.state.intake_provider = MockIntakeProvider()
    return client.post("/employee/interpret", data={"text": text}, headers=headers)


def test_employee_page_shows_the_ask_box(client):
    act_as(client, "ana")
    page = client.get("/employee")
    assert 'action="/employee/interpret"' in page.text
    assert "Ask Covered" in page.text


def test_interpret_prefills_the_check_form_and_decides_nothing(client):
    act_as(client, "ana")
    page = interpret(client, "Uber al aeropuerto ayer USD 45")
    assert page.status_code == 200
    assert 'value="45.00"' in page.text
    assert '<option value="ground_transport" selected>' in page.text
    assert 'value="Uber"' in page.text
    assert "No time in the text" in page.text
    assert "badge big" not in page.text  # no decision until the employee checks
    assert client.get("/expenses").json() == []


def test_missing_category_becomes_other_and_is_flagged(client):
    act_as(client, "ana")
    page = interpret(client, "algo de USD 30 ayer")
    assert '<option value="other" selected>' in page.text
    assert "set to Other; pick the right one." in page.text


def test_unsupported_currency_is_shown(client):
    act_as(client, "ana")
    page = interpret(client, "un almuerzo con el equipo de 35 lucas")
    assert "Unsupported currency" in page.text
    assert (
        'id="amount" name="amount" inputmode="decimal" placeholder="0.00" required value=""'
        in page.text
    )


def test_interpret_needs_an_identity_and_same_site(client):
    page = interpret(client, "taxi USD 20", Authorization="")
    assert "Choose who you are" in page.text
    act_as(client, "ana")
    blocked = interpret(
        client, "taxi USD 20", **{"Sec-Fetch-Site": "cross-site", "Authorization": ""}
    )
    assert blocked.status_code == 403


def test_too_long_text_shows_an_error(client):
    act_as(client, "ana")
    page = interpret(client, "x" * 501)
    assert "too long" in page.text
