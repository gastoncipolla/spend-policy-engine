"""Offline provider: replays hand-written results for the sample policies (SPEC §5.1).

Fixtures live in `fixtures/compilations/<sha256 of normalized text>.json`.
"""

from pathlib import Path

from covered.compiler.prompt import PROMPT_VERSION
from covered.compiler.result import CompileMeta, ProviderError, ProviderReply
from covered.compiler.text import text_sha256

DEFAULT_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "compilations"
"""`<repo>/fixtures/compilations` (this file is `<repo>/src/covered/compiler/`)."""

UNSUPPORTED_TEXT = "mock mode only supports the sample policies"


class MockProvider:
    name = "mock"

    def __init__(self, fixtures_dir: Path = DEFAULT_FIXTURES) -> None:
        self.fixtures_dir = fixtures_dir

    def propose(self, text: str) -> ProviderReply:
        meta = CompileMeta(
            provider=self.name,
            model="mock",
            prompt_version=PROMPT_VERSION,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
        )
        path = self.fixtures_dir / f"{text_sha256(text)}.json"
        if not path.is_file():
            raise ProviderError(UNSUPPORTED_TEXT, meta)
        return ProviderReply(payload=path.read_text(encoding="utf-8"), meta=meta)
