from __future__ import annotations
from typing import Any


def apply_modal_actions(
    records: list[dict[str, Any]],
    actions: dict[int, str],
    edits: dict[int, dict[str, str]],
) -> dict[str, list[dict[str, Any]]]:
    """
    Pure function: applies user review actions to a list of low-confidence records.

    actions: {index: "accepted" | "skipped" | "edited"}
    edits:   {index: {field_name: new_value}}  — only used when action == "edited"

    Returns {"accepted": [...], "skipped": [...]}.
    Accepted includes both "accepted" and "edited" records.
    Does not mutate the input records.
    """
    accepted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for i, rec in enumerate(records):
        action = actions.get(i, "accepted")
        r = dict(rec)
        if action == "skipped":
            skipped.append(r)
        else:
            if action == "edited" and i in edits:
                r.update(edits[i])
            accepted.append(r)

    return {"accepted": accepted, "skipped": skipped}
