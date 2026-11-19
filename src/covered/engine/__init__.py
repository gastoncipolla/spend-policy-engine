"""Pure, deterministic expense evaluation (SPEC §4).

Public interface: `evaluate` and `period_window`. No I/O, no clock, no LLM.
"""

from covered.engine.combine import UNCOVERED_MESSAGE, evaluate
from covered.engine.periods import PeriodWindow, period_window

__all__ = ["UNCOVERED_MESSAGE", "PeriodWindow", "evaluate", "period_window"]
