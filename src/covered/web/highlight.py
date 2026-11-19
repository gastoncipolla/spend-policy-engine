"""Mark each rule's clause inside the policy text, so finance sees them side by side."""

from markupsafe import Markup, escape


def highlight_clauses(text: str, labels: dict[str, str]) -> Markup:
    """Escape `text` and wrap every clause found in it with `<mark>` + its label.

    `labels` maps a clause to a short label ("R3"). Clauses are matched
    literally; a clause that is not found (or overlaps an earlier one) is
    simply not highlighted.
    """
    spans = []
    for clause, label in labels.items():
        start = text.find(clause) if clause else -1
        if start >= 0:
            spans.append((start, start + len(clause), label))

    html, cursor = [], 0
    for start, end, label in sorted(spans):
        if start < cursor:
            continue  # overlapping clause: keep the first one
        html.append(escape(text[cursor:start]))
        html.append(
            Markup('<mark id="clause-{0}">{1}<sup>{0}</sup></mark>').format(
                label, text[start:end]
            )
        )
        cursor = end
    html.append(escape(text[cursor:]))
    return Markup("").join(html)
