"""The `covered` CLI wraps the services (SPEC §8)."""

SUNDAY_LATE = "2026-11-22T23:30"  # no offset: company time


def test_seed_twice_gives_the_same_demo(cli):
    for _ in range(2):
        result = cli("seed")
        assert result.exit_code == 0, result.output
        assert "8 rules, 4 uncompilable, status active" in result.output
        assert "10 rules, 4 uncompilable, status active" in result.output


def test_seed_prints_the_demo_tokens(cli):
    result = cli("seed")
    for user in ("ana", "bruno", "carla", "diego", "fede"):
        assert f"Authorization: Bearer demo-{user}" in result.output
    assert "employee, finance" in result.output


def test_check_prints_outcome_reasons_and_clauses(seeded):
    result = seeded(
        "check",
        "--employee",
        "ana",
        "--amount",
        "95.50",
        "--category",
        "meals",
        "--at",
        SUNDAY_LATE,
    )
    assert result.exit_code == 0, result.output
    assert "REJECTED" in result.output
    assert '"Meals are reimbursed up to USD 80.00 per expense."' in result.output
    assert "Sun 23:30" in result.output
    assert "Keep this policy clause in mind" in result.output


def test_check_rejects_bad_amount_without_float(seeded):
    result = seeded(
        "check", "--employee", "ana", "--amount", "1.234", "--category", "meals"
    )
    assert result.exit_code != 0
    assert "more than 2 decimal places" in result.output


def test_unknown_employee_is_an_error(seeded):
    result = seeded(
        "check", "--employee", "zed", "--amount", "1", "--category", "meals"
    )
    assert result.exit_code == 1
    assert "unauthenticated: unknown user 'zed'" in result.output


def test_submit_with_key_is_idempotent_and_listed(seeded):
    args = (
        "submit",
        "--employee",
        "ana",
        "--amount",
        "120",
        "--category",
        "lodging",
        "--at",
        "2026-11-18T12:00",
        "--key",
        "cli-1",
    )
    first, second = seeded(*args), seeded(*args)
    assert "expense #1, key cli-1" in first.output
    assert "NEEDS APPROVAL" in first.output
    assert "expense #1 (replayed)" in second.output

    listed = seeded("expenses", "list", "--status", "pending", "--as", "fede")
    assert "USD 120.00" in listed.output and "[pending]" in listed.output

    resolved = seeded("expenses", "resolve", "1", "approved", "--as", "fede")
    assert resolved.exit_code == 0 and "[approved]" in resolved.output
    again = seeded("expenses", "resolve", "1", "rejected", "--as", "fede")
    assert again.exit_code == 1 and "invalid_transition" in again.output


def test_submit_generates_a_key_when_missing(seeded):
    result = seeded(
        "submit",
        "--employee",
        "carla",
        "--amount",
        "20",
        "--category",
        "meals",
        "--at",
        "2026-11-18T12:00",
    )
    assert result.exit_code == 0, result.output
    assert "expense #1, key " in result.output


def test_policy_show_lists_and_details(seeded):
    listing = seeded("policy", "show", "--as", "fede")
    assert "Sales" in listing.output and "Engineering" in listing.output
    detail = seeded("policy", "show", "engineering", "--as", "fede")
    assert "Engineering — version 1 (active)" in detail.output
    assert "Entertainment: not reimbursable" in detail.output
    assert "Uncovered categories (always need approval): other" in detail.output


def test_policy_compile_and_activate_on_active_version_are_refused(seeded):
    compiled = seeded("policy", "compile", "sales", "--as", "fede")
    assert compiled.exit_code == 1 and "version_immutable" in compiled.output
    activated = seeded("policy", "activate", "sales", "--as", "fede")
    assert activated.exit_code == 1 and "version_immutable" in activated.output


PENDING_AIRFARE = (
    "submit",
    "--employee",
    "ana",
    "--amount",
    "300",
    "--category",
    "airfare",
    "--at",
    "2026-11-18T10:00",
)


def test_as_goes_through_the_same_authorization(seeded):
    assert seeded(*PENDING_AIRFARE).exit_code == 0

    as_other = seeded(*PENDING_AIRFARE, "--as", "carla")
    assert as_other.exit_code == 1 and "forbidden" in as_other.output

    own = seeded("expenses", "resolve", "1", "approved", "--as", "ana")
    assert own.exit_code == 1 and "separation of duties" in own.output
    hidden = seeded("expenses", "resolve", "1", "approved", "--as", "carla")
    assert hidden.exit_code == 1 and "not_found" in hidden.output

    assert "No expenses." in seeded("expenses", "list", "--as", "diego").output
    by_manager = seeded("expenses", "resolve", "1", "approved", "--as", "bruno")
    assert by_manager.exit_code == 0, by_manager.output


def test_policy_commands_default_to_finance_and_refuse_others(seeded):
    refused = seeded("policy", "activate", "sales", "--as", "ana")
    assert refused.exit_code == 1 and "forbidden: only finance" in refused.output
    listing = seeded("policy", "show", "--as", "ana").output
    assert "Sales" in listing and "Engineering" not in listing


def test_finance_capable_commands_require_an_explicit_user(seeded):
    # Deny by default: no silent "act as finance" when --as is omitted.
    for args in (
        ("expenses", "list"),
        ("policy", "show"),
        ("policy", "activate", "sales"),
    ):
        result = seeded(*args)
        assert result.exit_code != 0
        assert "--as" in result.output
