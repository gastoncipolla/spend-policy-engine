"""Eval cases: a policy text plus the hand-written expected compilation.

One TOML file per case in `cases/`:

    description = "..."
    policy = \"\"\"...\"\"\"            # or: policy_file = "fixtures/policies/sales.md"

    [[rule]]                        # this clause must compile to this rule
    clause = "..."
    params = { type = "max_amount", category = "meals", amount_minor = 5000 }
    also_accept = [ {...} ]         # optional: other params that are also right
    flags = ["conflict"]            # optional: expected validation flags

    [[uncompilable]]                # this clause must be uncompilable
    clause = "..."
    effect = "requires_review"      # optional: expected proposed effect

    [[not_rule]]                    # this clause must not become a rule
    clause = "..."                  # (ignored or uncompilable are both fine)
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import TypeAdapter

from covered.compiler.text import clause_in_text
from covered.domain import RuleParams, UncompilableEffect

REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = Path(__file__).resolve().parent / "cases"

Kind = Literal["rule", "uncompilable", "not_rule"]
_PARAMS = TypeAdapter(RuleParams)


def canonical(params: Any) -> dict[str, Any]:
    """Params as a comparable dict: validated, defaults filled, lists sorted."""
    data = _PARAMS.validate_python(params).model_dump(mode="json")
    return {
        key: sorted(value) if isinstance(value, list) else value
        for key, value in data.items()
    }


@dataclass(frozen=True)
class Expectation:
    kind: Kind
    clause: str
    accepted: tuple[dict[str, Any], ...] = ()
    """Canonical params that count as correct (rules only; the first is the primary)."""
    flags: tuple[str, ...] = ()
    effect: UncompilableEffect | None = None


@dataclass(frozen=True)
class Case:
    name: str
    description: str
    policy: str
    expectations: tuple[Expectation, ...]


def load_case(path: Path) -> Case:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if "policy_file" in data:
        policy = (REPO_ROOT / data["policy_file"]).read_text(encoding="utf-8")
    else:
        policy = data["policy"]
    expectations = [
        Expectation(
            kind="rule",
            clause=item["clause"],
            accepted=tuple(
                canonical(p) for p in [item["params"], *item.get("also_accept", [])]
            ),
            flags=tuple(item.get("flags", ())),
        )
        for item in data.get("rule", [])
    ]
    expectations += [
        Expectation(
            kind="uncompilable",
            clause=item["clause"],
            effect=UncompilableEffect(item["effect"]) if "effect" in item else None,
        )
        for item in data.get("uncompilable", [])
    ]
    expectations += [
        Expectation(kind="not_rule", clause=item["clause"])
        for item in data.get("not_rule", [])
    ]
    for expectation in expectations:
        if not clause_in_text(expectation.clause, policy):
            raise ValueError(f"{path.name}: clause not in policy: {expectation.clause}")
    return Case(path.stem, data["description"], policy, tuple(expectations))


def load_cases(directory: Path = CASES_DIR) -> list[Case]:
    return [load_case(path) for path in sorted(directory.glob("*.toml"))]
