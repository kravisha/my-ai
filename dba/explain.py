"""§43: the structured result, said in a sentence.

    *"I updated customer C-104's phone number. No other fields were changed."*
    *"The structured response remains authoritative."*

Both halves matter, and the second one is why this module is generated from the
response rather than written alongside it. A sentence composed independently of
the structured result is a second source of truth that will eventually disagree
with the first, and the one people read is the sentence.

So every line here is built from fields the response actually carries. There is
no model call and no template that can assert something the response does not
say - the same reason `app/learning/engine.explain_how_i_learn` is generated
from the code it describes.
"""

from __future__ import annotations

from dba import contract


def explain(response: contract.Response) -> str:
    """One or two plain sentences describing exactly what the response says."""
    if response.needs_answer:
        return _clarification(response)
    if response.status == contract.STATUS_ERROR:
        return _error(response)
    return _success(response)


def _success(response: contract.Response) -> str:
    what = response.entity_type or "record"
    where = f" {response.entity_id}" if response.entity_id else ""
    result = response.result if isinstance(response.result, dict) else {}

    if not response.changed:
        if result.get("committed") is False:
            count = result.get("matched_records")
            if count is not None:
                return (f"Nothing was changed. That would affect {count} "
                        f"{what} record(s).")
            would = result.get("would_change") or result.get("would_create")
            return (f"Nothing was changed. That would "
                    f"{'change ' + ', '.join(sorted(would)) if isinstance(would, dict) and would else 'create a new ' + what}.")
        if "count" in result and "matches" in result:
            return f"Found {result['count']} {what} record(s)."
        if "count" in result:
            return f"There are {result['count']} {what} record(s)."
        if "events" in result:
            return f"{result['count']} recorded change(s) to {what}{where}."
        if "acceptable" in result:
            return ("That write would be accepted." if result["acceptable"]
                    else f"That write would be rejected: "
                         f"{len(result.get('problems') or [])} problem(s).")
        if response.warnings:
            return f"No change to {what}{where}. {response.warnings[0]}"
        return f"Read {what}{where}."

    action = response.action
    if action == contract.CREATE:
        return f"I created {what}{where}."
    if action == contract.UPDATE:
        fields = sorted((result.get("changed_fields") or {}))
        if fields:
            listed = _and_list(fields)
            return (f"I updated {what}{where}'s {listed}. No other fields were "
                    f"changed.")
        return f"I updated {what}{where}."
    if action in (contract.ARCHIVE, contract.DELETE_AUTHORIZED):
        verb = "archived" if action == contract.ARCHIVE else "deleted"
        affected = result.get("affected", 1)
        also = result.get("already_in_that_state") or 0
        sentence = f"I {verb} {affected} {what} record(s)."
        if also:
            sentence += f" {also} was already {verb}."
        return sentence
    if action == contract.LINK:
        return f"I linked those two records."
    if action == contract.UNLINK:
        return f"I removed that link."
    return f"I completed {action} on {what}{where}."


def _clarification(response: contract.Response) -> str:
    asked = response.clarification or {}
    question = asked.get("question", "I need one more detail.")
    pending = asked.get("pending_action")
    options = asked.get("options") or []
    sentence = f"I have not changed anything. {question}"
    if options and all(isinstance(option, dict) for option in options):
        rendered = [_option(option) for option in options[:5]]
        sentence += " " + "; ".join(rendered) + "."
        if len(options) > 5:
            sentence += f" (and {len(options) - 5} more)"
    if pending:
        sentence += f" Waiting to: {pending}."
    return sentence


def _error(response: contract.Response) -> str:
    error = response.error or {}
    code = error.get("error_code", "error")
    message = error.get("message", "")
    lead = {
        contract.PERMISSION_DENIED: "I was not allowed to do that.",
        contract.NOT_FOUND: "I could not find that.",
        contract.DUPLICATE_DETECTED: "That would duplicate an existing record.",
        contract.CONFLICT_DETECTED: "That conflicts with something already recorded.",
        contract.VALIDATION_ERROR: "That request was not valid.",
        contract.DATABASE_UNAVAILABLE: "I could not reach the database, so nothing happened.",
        contract.TRANSACTION_FAILED: "The change was rolled back; nothing was applied.",
    }.get(code, "That did not work.")
    return f"{lead} {message}".strip()


def _option(option: dict) -> str:
    if "field" in option and "set_to" in option:
        return f"set {option['field']} to {option['set_to']!r}"
    if "field" in option and "keep" in option:
        return f"keep {option['field']} as {option['keep']!r}"
    if "field" in option:
        return f"{option['field']}"
    # Every non-id field, not just the first. Two records offered as a choice
    # are often identical in their label - that is usually *why* the question
    # was asked - so a rendering that showed only the name would print the same
    # words twice and ask the reader to pick between them.
    described = ", ".join(f"{value}" for key, value in option.items()
                          if key != "id" and value)
    identifier = option.get("id")
    if described and identifier:
        return f"{described} ({identifier})"
    return str(identifier or described or option)


def _and_list(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"
