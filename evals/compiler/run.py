"""Run the compiler eval: every case x model x repeat, scored clause by clause.

    uv run python -m evals.compiler.run --models claude-haiku-5-5 claude-sonnet-5-5
    uv run python -m evals.compiler.run --provider mock   # offline, sample cases only

Writes `results/<name>.json` (every raw output and label) and `results/<name>.md`
(summary). Real runs need `ANTHROPIC_API_KEY` and spend money: the runner stops
before a call could take the total past `--budget-usd`.
"""

import argparse
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean

from covered.compiler import (
    PROMPT_VERSION,
    AnthropicProvider,
    CompileOutcome,
    MockProvider,
    Provider,
    compile_text,
)
from covered.compiler.anthropic_provider import DEFAULT_MODEL, PRICES_PER_MTOK
from evals.compiler.cases import Case, load_cases
from evals.compiler.score import CORRECT, UNSAFE_LABELS, CaseScore, score

RESULTS_DIR = Path(__file__).resolve().parent / "results"
FIRST_CALL_RESERVE = Decimal("0.10")
"""Budget kept free before a model's first call (later: its most expensive call)."""


@dataclass
class Run:
    model: str
    case: str
    repeat: int
    outcome: CompileOutcome
    score: CaseScore


@dataclass
class Report:
    runs: list[Run]
    spent_usd: Decimal
    aborted: bool


def run_eval(
    cases: list[Case],
    models: list[str],
    repeats: int,
    make_provider: Callable[[str], Provider],
    budget_usd: Decimal,
    log: Callable[[str], None] = print,
) -> Report:
    """Repeat-major order, so a run stopped by the budget still covers every case."""
    runs: list[Run] = []
    spent = Decimal(0)
    worst: dict[str, Decimal] = {}  # most expensive call so far, per model
    providers = {model: make_provider(model) for model in models}
    for repeat in range(1, repeats + 1):
        for model in models:
            for case in cases:
                if spent + worst.get(model, FIRST_CALL_RESERVE) > budget_usd:
                    log(f"budget: spent {spent:.4f}, next call may pass {budget_usd}")
                    return Report(runs, spent, aborted=True)
                outcome = compile_text(case.policy, providers[model])
                cost = outcome.meta.cost_usd or Decimal(0)
                spent += cost
                worst[model] = max(cost, worst.get(model, cost))
                scored = score(case, outcome)
                runs.append(Run(model, case.name, repeat, outcome, scored))
                log(
                    f"{model} #{repeat} {case.name}: "
                    f"{scored.correct}/{len(scored.items)} "
                    f"{outcome.meta.latency_ms} ms ${cost:.4f} (total ${spent:.4f})"
                )
    return Report(runs, spent, aborted=False)


def summarize(runs: list[Run]) -> dict[str, dict]:
    summary = {}
    for model in dict.fromkeys(run.model for run in runs):
        mine = [run for run in runs if run.model == model]
        labels = Counter(item.label for run in mine for item in run.score.items)
        items = sum(labels.values())
        extra = sum(len(run.score.extra_rules) for run in mine)
        latencies = [run.outcome.meta.latency_ms or 0 for run in mine]
        cost = sum(
            (run.outcome.meta.cost_usd or Decimal(0) for run in mine), Decimal(0)
        )
        summary[model] = {
            "calls": len(mine),
            "compile_failures": sum(not run.outcome.ok for run in mine),
            "items": items,
            "correct": labels[CORRECT],
            "accuracy": round(labels[CORRECT] / items, 3) if items else None,
            "unsafe": sum(labels[label] for label in UNSAFE_LABELS) + extra,
            "extra_rules": extra,
            "labels": dict(sorted(labels.items())),
            "consistency": consistency(mine),
            "latency_ms_mean": round(mean(latencies)) if latencies else None,
            "latency_ms_max": max(latencies, default=None),
            "cost_usd_total": str(cost),
            "cost_usd_per_policy": str(round(cost / len(mine), 5)) if mine else None,
        }
    return summary


def consistency(runs: list[Run]) -> float | None:
    """Share of expected clauses with the same label and params in every repeat."""
    by_case: dict[str, list[CaseScore]] = {}
    for run in runs:
        by_case.setdefault(run.case, []).append(run.score)
    same = total = 0
    for scores in by_case.values():
        if len(scores) < 2:
            continue
        for index in range(len(scores[0].items)):
            outcomes = {
                (s.items[index].label, json.dumps(s.items[index].got, sort_keys=True))
                for s in scores
            }
            same += len(outcomes) == 1
            total += 1
    return round(same / total, 3) if total else None


def to_json(report: Report, summary: dict, args: dict) -> dict:
    return {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "prompt_version": PROMPT_VERSION,
        "args": args,
        "spent_usd": str(report.spent_usd),
        "aborted": report.aborted,
        "summary": summary,
        "runs": [
            {
                "model": run.model,
                "case": run.case,
                "repeat": run.repeat,
                "ok": run.outcome.ok,
                "error": run.score.error,
                "meta": run.outcome.meta.model_dump(mode="json"),
                "rules": [
                    r.model_dump(mode="json") for r in getattr(run.outcome, "rules", ())
                ],
                "uncompilable": [
                    u.model_dump(mode="json")
                    for u in getattr(run.outcome, "uncompilable", ())
                ],
                "items": [asdict(item) for item in run.score.items],
                "extra_rules": run.score.extra_rules,
            }
            for run in report.runs
        ],
    }


def to_markdown(data: dict) -> str:
    summary = data["summary"]
    lines = [
        "# Compiler eval",
        "",
        f"- Created: {data['created_at']} · prompt `{data['prompt_version']}` · "
        f"repeats: {data['args']['repeats']} · spent: USD {data['spent_usd']}"
        + (" · **aborted by budget**" if data["aborted"] else ""),
        (
            "- Small sample: hand-written, fictional policies; a handful of runs per model. "
            "Read it as a sanity check, not a benchmark."
        ),
        "",
        (
            "| Model | Accuracy | Correct / items | Unsafe | Consistency | "
            "Failures | Cost / policy (USD) | Latency mean / max (s) |"
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    for model, s in summary.items():
        lines.append(
            f"| `{model}` | {_pct(s['accuracy'])} | {s['correct']} / {s['items']} | "
            f"{s['unsafe']} | {_pct(s['consistency'])} | {s['compile_failures']} | "
            f"{s['cost_usd_per_policy']} | "
            f"{_seconds(s['latency_ms_mean'])} / {_seconds(s['latency_ms_max'])} |"
        )
    lines += [
        "",
        (
            "Accuracy: expected clauses labeled `correct`. Unsafe: wrong type, params or "
            "conflict flag, a rule where an uncompilable clause was expected, plus rules "
            "for clauses no case expects. Consistency: expected clauses with the same "
            "label and params in every repeat."
        ),
        "",
        "## Per case (correct / items, one value per repeat)",
        "",
        "| Case | " + " | ".join(f"`{m}`" for m in summary) + " |",
        "|---|" + "---|" * len(summary),
    ]
    cases = list(dict.fromkeys(run["case"] for run in data["runs"]))
    for case in cases:
        cells = []
        for model in summary:
            runs = [
                r for r in data["runs"] if r["case"] == case and r["model"] == model
            ]
            cells.append(" · ".join(_case_cell(r) for r in runs))
        lines.append(f"| {case} | " + " | ".join(cells) + " |")
    lines += ["", "## Not correct", ""]
    for model in summary:
        misses = Counter(
            (run["case"], item["label"], item["clause"])
            for run in data["runs"]
            if run["model"] == model
            for item in run["items"]
            if item["label"] != CORRECT
        )
        extras = Counter(
            (run["case"], "extra_rule", clause)
            for run in data["runs"]
            if run["model"] == model
            for clause in run["extra_rules"]
        )
        lines.append(f"### `{model}`")
        lines.append("")
        for (case, label, clause), count in sorted((misses + extras).items()):
            lines.append(f"- {case} · **{label}** ×{count}: {clause}")
        if not misses and not extras:
            lines.append("- none")
        lines.append("")
    return "\n".join(lines)


def _case_cell(run: dict) -> str:
    if not run["ok"]:
        return "failed"
    correct = sum(item["label"] == CORRECT for item in run["items"])
    return f"{correct}/{len(run['items'])}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _seconds(ms: int | None) -> str:
    return "n/a" if ms is None else f"{ms / 1000:.1f}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", nargs="+", default=[DEFAULT_MODEL])
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument(
        "--provider", choices=("anthropic", "mock"), default="anthropic"
    )
    parser.add_argument("--budget-usd", type=Decimal, default=Decimal("1.80"))
    parser.add_argument("--name", default=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--out-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)

    cases = load_cases()
    if args.provider == "mock":
        # The mock only knows the sample policies.
        cases = [case for case in cases if case.name.startswith("sample_")]
        models = ["mock"]

        def make_provider(model: str) -> Provider:
            return MockProvider()
    else:
        unknown = [m for m in args.models if m not in PRICES_PER_MTOK]
        if unknown:
            parser.error(f"no price for {unknown}: cannot enforce the budget")
        models = args.models

        def make_provider(model: str) -> Provider:
            return AnthropicProvider(model=model)

    report = run_eval(cases, models, args.repeats, make_provider, args.budget_usd)
    data = to_json(report, summarize(report.runs), _args(args, models))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / f"{args.name}.json"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    md_path = args.out_dir / f"{args.name}.md"
    md_path.write_text(to_markdown(data) + "\n")
    print(f"spent USD {report.spent_usd:.4f}; wrote {json_path} and {md_path}")


def _args(args: argparse.Namespace, models: list[str]) -> dict:
    return {
        "provider": args.provider,
        "models": models,
        "repeats": args.repeats,
        "budget_usd": str(args.budget_usd),
    }


if __name__ == "__main__":
    main()
