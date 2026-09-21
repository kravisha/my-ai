"""The published API contract (§25), generated from the declaration.

    *"Every published API should define: purpose, request structure, response
    structure, required fields, optional fields, validation rules, permissions,
    error conditions, version, and examples. APIs are contracts between the DBA
    Agent and the other agents."*

All ten, generated. Not written alongside the capability - generated from it,
so a contract cannot describe a field the schema does not have. That is the
same rule `app/learning/engine.explain_how_i_learn` follows and the reason it
is trustworthy: a document maintained by hand beside a declaration is a
document that will eventually disagree with it, and the one people read is the
document.
"""

from __future__ import annotations

from dba import capability as capability_module, contract, entities

# What each operation does, in the words a consuming agent needs.
OPERATION_PURPOSE = {
    contract.CREATE: "store a new record",
    contract.GET: "read one record by its identifier",
    contract.FIND: "read the records matching field values",
    contract.SEARCH: "read the records whose text matches",
    contract.LIST: "read a page of records",
    contract.COUNT: "how many records there are",
    contract.UPDATE: "change fields on one record",
    contract.ARCHIVE: "retire a record without destroying it",
    contract.DELETE_AUTHORIZED: "remove a record, if authorised",
    contract.HISTORY: "every recorded change to one record",
    contract.VALIDATE: "ask whether a write would be accepted, without writing",
    contract.LINK: "relate this record to another",
    contract.UNLINK: "remove a relation",
}


def contract_for(declared: capability_module.Capability) -> dict:
    """§25's ten elements for one capability."""
    entity_type = declared.entity_type
    optional = sorted(set(entity_type.fields) - set(entity_type.required))
    return {
        "capability": declared.name,
        "version": declared.version,
        "purpose": declared.purpose,
        "base_path": declared.route_prefix,
        "operations": [
            {
                "operation": action,
                "path": f"{declared.route_prefix}/{action}",
                "method": "POST",
                "purpose": OPERATION_PURPOSE.get(action, action),
                "changes_data": action in contract.WRITING_ACTIONS,
            }
            for action in declared.operations
        ],
        "request": {
            "shape": {
                "data": "the record's fields, for create and update",
                "entity_id": "the identifier, for get/update/archive/history",
                "criteria": "field values to match, for find; {text} for search",
                "request_id": "an idempotency key; replaying it returns the "
                              "first result rather than writing twice",
                "dry_run": "true to be told what would happen, changing nothing",
                "reason": "why, recorded in the audit trail",
                "confirmed": "true to accept a destructive scope the DBA "
                             "reported back",
            },
            "required_fields": list(entity_type.required),
            "optional_fields": optional,
            "field_types": dict(sorted(entity_type.fields.items())),
        },
        "response": {
            "shape": {
                "status": "success | clarification_required | error",
                "changed": "whether the database actually changed; false on a "
                           "replay, a dry run and a write that made no "
                           "difference",
                "entity_id": "the record this concerned",
                "result": "the operation's payload",
                "warnings": "things worth knowing that are not failures",
                "clarification": "the question, when the DBA will not guess",
                "error": "error_code, message, retryable, details",
                "timestamp": "when the response was produced",
            },
            "clarification_is_http_200": True,
        },
        "validation": _validation(entity_type),
        "permissions": {
            agent: sorted(held) for agent, held in sorted(declared.grants.items())
        },
        "errors": _errors(declared),
        "retention": declared.retention.to_dict()
        | {"described": declared.retention.describe()},
        "relationships": [r.to_dict() for r in declared.relationships],
        "examples": list(declared.examples) or [],
        "notes": list(declared.notes),
    }


def _validation(entity_type: entities.EntityType) -> list[str]:
    rules = [f"{name} is required" for name in entity_type.required]
    for name, declared in sorted(entity_type.fields.items()):
        rules.append(f"{name} must be {declared}")
    if entity_type.statuses:
        rules.append(f"status must be one of "
                     f"{', '.join(entity_type.statuses)}")
    for name in entity_type.identifying:
        rules.append(f"{name} must not already belong to another record")
    rules.append("a field this capability does not declare is refused, never "
                 "stored silently")
    return rules


def _errors(declared: capability_module.Capability) -> list[dict]:
    possible = [
        (contract.VALIDATION_ERROR, "the request does not satisfy the rules above"),
        (contract.PERMISSION_DENIED,
         "the asking agent is not granted this operation on this capability"),
        (contract.NOT_FOUND, "no live record matches"),
        (contract.DATABASE_UNAVAILABLE,
         "the store could not be reached; nothing was written"),
        (contract.INTERNAL_ERROR, "an unexpected failure; nothing was written"),
    ]
    if declared.entity_type.identifying:
        possible.insert(2, (contract.DUPLICATE_DETECTED,
                            f"a record already holds that "
                            f"{'/'.join(declared.entity_type.identifying)}"))
    if contract.UPDATE in declared.operations:
        possible.append((contract.CONFLICT_DETECTED,
                         "an idempotency key was reused for a different request"))
    return [{"error_code": code,
             "means": means,
             "retryable": code in contract.RETRYABLE_CODES}
            for code, means in possible]


def markdown(declared: capability_module.Capability) -> str:
    """The contract as documentation (§5's "document APIs")."""
    spec = contract_for(declared)
    lines = [
        f"# {declared.name} — v{declared.version}",
        "",
        declared.purpose,
        "",
        f"**Base path:** `{spec['base_path']}`  ",
        f"**Retention:** {spec['retention']['described']}",
        "",
        "## Operations",
        "",
        "| Operation | Path | What it does | Writes? |",
        "|---|---|---|---|",
    ]
    for operation in spec["operations"]:
        lines.append(
            f"| `{operation['operation']}` | `{operation['path']}` | "
            f"{operation['purpose']} | "
            f"{'yes' if operation['changes_data'] else 'no'} |")

    lines += ["", "## Fields", "", "| Field | Type | Required |", "|---|---|---|"]
    required = set(spec["request"]["required_fields"])
    for name, declared_type in spec["request"]["field_types"].items():
        lines.append(f"| `{name}` | {declared_type} | "
                     f"{'yes' if name in required else 'no'} |")

    lines += ["", "## Who may do what", "", "| Agent | Permissions |", "|---|---|"]
    for agent, held in spec["permissions"].items():
        lines.append(f"| `{agent}` | {', '.join(held)} |")

    lines += ["", "## Validation", ""]
    lines += [f"- {rule}" for rule in spec["validation"]]

    lines += ["", "## Errors", "", "| Code | Means | Retryable |", "|---|---|---|"]
    for error in spec["errors"]:
        lines.append(f"| `{error['error_code']}` | {error['means']} | "
                     f"{'yes' if error['retryable'] else 'no'} |")

    if spec["examples"]:
        lines += ["", "## Example", "", "```json"]
        import json

        lines.append(json.dumps(spec["examples"][0], indent=2))
        lines.append("```")

    lines += ["", "---", "",
              "A `clarification_required` response is HTTP **200**. It is not a "
              "failure — the DBA understood the request and is asking a "
              "question, and nothing was written.", ""]
    return "\n".join(lines)
