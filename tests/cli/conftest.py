"""CLI tests run against a temporary database (env COVERED_DB) with the mock provider."""

import pytest
from typer.testing import CliRunner

from covered.cli.main import app


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv("COVERED_DB", str(tmp_path / "cli.db"))
    monkeypatch.setenv("COVERED_PROVIDER", "mock")
    runner = CliRunner()

    def run(*args: str):
        return runner.invoke(app, list(args))

    return run


@pytest.fixture
def seeded(cli):
    result = cli("seed")
    assert result.exit_code == 0, result.output
    return cli
