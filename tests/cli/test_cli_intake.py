"""`covered expenses parse`: a draft as JSON, acting as a known user."""

import json


def test_parse_prints_a_draft(seeded):
    result = seeded("expenses", "parse", "taxi ayer USD 20", "--as", "ana")
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert body["draft"]["amount_minor"] == 2000
    assert body["draft"]["category"] == "ground_transport"
    assert body["provider"] == "mock"


def test_parse_requires_a_known_user(seeded):
    result = seeded("expenses", "parse", "taxi ayer USD 20", "--as", "nobody")
    assert result.exit_code == 1
