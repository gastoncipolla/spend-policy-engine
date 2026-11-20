"""Score "Ask Covered" intake on the hand-labeled cases in cases.yaml.

    uv run --with pyyaml python evals/intake/run.py --provider mock
    uv run --with pyyaml python evals/intake/run.py --provider anthropic \
        --model claude-haiku-5-5 --repeats 2 --budget 0.05

The anthropic provider needs ANTHROPIC_API_KEY in the environment. Each run
writes `results/<label>.json` (every case, every repeat) and regenerates
`results/summary.md` from all the JSON files. `--budget` is a hard stop in USD
for this run, measured from the responses' token usage: the runner stops before
a call that could exceed it (estimated as twice the most expensive call so far).
"""

import argparse
import json
import statistics
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from covered.intake import (
    AnthropicIntakeProvider,
    IntakeResult,
    MockIntakeProvider,
    parse_expense_text,
)

HERE = Path(__file__).parent
RESULTS = HERE / "results"
TZ = ZoneInfo("America/Argentina/Buenos_Aires")
FIELDS = ("category", "amount_minor", "occurred_on", "merchant")
KEY_FLAGS = {
    "unsupported_currency",
    "multiple_expenses",
    "future_date",
    "amount_not_in_text",
    "unknown_category",
    "currency_assumed",
    "invalid_amount",
    "invalid_date",
    "not_in_text",
    "provider_error",
}
"""Flags that are scored. `time_not_stated` is informational and not scored."""
FIRST_CALL_ESTIMATE = Decimal("0.01")


def actual_fields(result: IntakeResult) -> dict:
    draft = result.draft
    occurred_on: date | None = (
        draft.occurred_at.astimezone(TZ).date() if draft.occurred_at else None
    )
    return {
        "category": draft.category.value if draft.category else None,
        "amount_minor": draft.amount_minor,
        "occurred_on": occurred_on.isoformat() if occurred_on else None,
        "merchant": draft.merchant,
        "missing": list(result.missing),
        "flags": sorted({flag.code for flag in result.flags} & KEY_FLAGS),
    }


def score(expected: dict, actual: dict) -> dict:
    """Per-field correctness for the keys the case labels."""
    checks = {}
    for field in FIELDS:
        if field in expected:
            want, got = expected[field], actual[field]
            if field == "merchant" and want and got:
                want, got = want.casefold(), got.casefold()
            checks[field] = want == got
    if "missing" in expected:
        checks["missing"] = sorted(expected["missing"]) == sorted(actual["missing"])
    if "flags" in expected:
        checks["flags"] = sorted(expected["flags"]) == actual["flags"]
    return checks


def run(args: argparse.Namespace) -> dict:
    spec = yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))
    now = datetime.fromisoformat(spec["now"])
    if args.provider == "mock":
        provider = MockIntakeProvider()
    else:
        provider = AnthropicIntakeProvider(model=args.model)
    spent, worst, records, stopped = Decimal(0), FIRST_CALL_ESTIMATE, [], False
    for repeat in range(args.repeats):
        for case in spec["cases"]:
            if args.provider != "mock" and spent + 2 * worst > args.budget:
                stopped = True
                break
            result = parse_expense_text(case["text"], provider, now=now, tz=TZ)
            cost = result.meta.cost_usd or Decimal(0)
            spent += cost
            worst = max(worst, cost)
            actual = actual_fields(result)
            records.append(
                {
                    "id": case["id"],
                    "repeat": repeat,
                    "text": case["text"],
                    "expected": case["expected"],
                    "actual": actual,
                    "checks": score(case["expected"], actual),
                    "all_flags": [flag.code for flag in result.flags],
                    "latency_ms": result.meta.latency_ms,
                    "input_tokens": result.meta.input_tokens,
                    "output_tokens": result.meta.output_tokens,
                    "cost_usd": str(cost),
                }
            )
            print(f"{case['id']:<36} {_mark(records[-1]['checks'])}", file=sys.stderr)
        if stopped:
            break
    return {
        "label": args.label,
        "provider": args.provider,
        "model": provider.model if args.provider != "mock" else "mock",
        "prompt_version": result.meta.prompt_version,
        "now": spec["now"],
        "repeats_requested": args.repeats,
        "stopped_by_budget": stopped,
        "budget_usd": str(args.budget),
        "spent_usd": str(spent),
        "summary": summarize(records),
        "records": records,
    }


def _mark(checks: dict) -> str:
    return " ".join(f"{k}={'ok' if v else 'FAIL'}" for k, v in checks.items())


def summarize(records: list[dict]) -> dict:
    per_field = {}
    for field in (*FIELDS, "missing", "flags"):
        values = [r["checks"][field] for r in records if field in r["checks"]]
        if values:
            per_field[field] = {"correct": sum(values), "total": len(values)}
    field_checks = [ok for r in records for f, ok in r["checks"].items() if f in FIELDS]
    latencies = [r["latency_ms"] for r in records if r["latency_ms"] is not None]
    return {
        "calls": len(records),
        "cases_fully_correct": sum(all(r["checks"].values()) for r in records),
        "field_accuracy": _ratio(sum(field_checks), len(field_checks)),
        "per_field": per_field,
        "latency_ms_p50": statistics.median(latencies) if latencies else None,
        "latency_ms_max": max(latencies) if latencies else None,
        "cost_usd_total": str(sum(Decimal(r["cost_usd"]) for r in records)),
        "cost_usd_per_call": str(
            (sum(Decimal(r["cost_usd"]) for r in records) / len(records)).quantize(
                Decimal("0.000001")
            )
            if records
            else 0
        ),
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def write_summary() -> None:
    runs = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(RESULTS.glob("*.json"))
    ]
    lines = [
        "# Ask Covered: intake eval results",
        "",
        "Generated by `evals/intake/run.py` from the JSON files in this folder.",
        "Small sample: 20 hand-labeled sentences, 1-2 repeats. Treat differences of",
        "a case or two as noise, not as a ranking.",
        "",
        (
            "| run | model | calls | fully correct | field accuracy | missing ok | "
            "flags ok | p50 latency (ms) | max latency (ms) | cost USD | USD/call |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for item in runs:
        s = item["summary"]
        per = s["per_field"]
        lines.append(
            f"| {item['label']} | {item['model']} | {s['calls']} | "
            f"{s['cases_fully_correct']}/{s['calls']} | {s['field_accuracy']} | "
            f"{_frac(per.get('missing'))} | {_frac(per.get('flags'))} | "
            f"{s['latency_ms_p50']} | {s['latency_ms_max']} | "
            f"{s['cost_usd_total']} | {s['cost_usd_per_call']} |"
        )
    lines += ["", "## Failures", ""]
    for item in runs:
        failures = [r for r in item["records"] if not all(r["checks"].values())]
        lines.append(f"### {item['label']} ({len(failures)} failing calls)")
        lines.append("")
        for r in failures:
            wrong = [f for f, ok in r["checks"].items() if not ok]
            details = ", ".join(
                f"{f}: expected {r['expected'].get(f)!r}, got {r['actual'].get(f)!r}"
                for f in wrong
            )
            lines.append(f"- `{r['id']}` (repeat {r['repeat']}): {details}")
        lines.append("")
    (RESULTS / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def _frac(item: dict | None) -> str:
    return f"{item['correct']}/{item['total']}" if item else "-"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["mock", "anthropic"], default="mock")
    parser.add_argument("--model", default=None)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--budget", type=Decimal, default=Decimal("0.05"))
    parser.add_argument("--label", default=None)
    args = parser.parse_args()
    args.label = args.label or (args.model or args.provider)
    RESULTS.mkdir(exist_ok=True)
    report = run(args)
    path = RESULTS / f"{args.label}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_summary()
    print(json.dumps(report["summary"], indent=2), file=sys.stderr)
    print(f"spent USD {report['spent_usd']}", file=sys.stderr)


if __name__ == "__main__":
    main()
