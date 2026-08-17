"""Pure formatting for the Controller control panel.

Split out from panel/app.py so the rendering decisions that actually matter -
how a dormant agent is distinguished from an unhealthy one, how two
unreconciled findings are laid out - are testable without constructing a Tk
window. app.py is then only widgets, polling, and HTTP.
"""

import json

# Health is a claim about a running process, so it has three states, not two.
# A dormant agent is not unhealthy; it has been deliberately stood down and has
# no process to be healthy about. Collapsing that into "unhealthy" would show a
# fault where there is a decision.
HEALTH_LABELS = {True: "healthy", False: "UNHEALTHY", None: "n/a (dormant)"}


def agent_row(agent: dict) -> str:
    """One roster line. lifecycle and process are always shown as two separate
    columns - the whole point of the two-axis model is that they answer
    different questions, and a merged column would hide the case the model
    exists for: a dormant agent and a crashed one both have no process, but
    only one of them should be refilled."""
    age = agent["heartbeat_age_seconds"]
    return "{:<14} {:<11} {:<9} {:<9} {:>8}".format(
        agent["identity"],
        agent["role"],
        agent["lifecycle_state"],
        agent["process_state"],
        "-" if age is None else f"{age:.1f}s",
    )


AGENT_HEADER = "{:<14} {:<11} {:<9} {:<9} {:>8}".format(
    "identity", "role", "lifecycle", "process", "beat"
)


def format_agent_detail(body: dict) -> str:
    """Addendum 14 §6's answers, laid out for a human.

    `answered_by` is printed prominently rather than buried. When the answer
    comes from the organizational record the panel must say so - presenting a
    database read as the agent's own reply would be a small lie that gets
    load-bearing as soon as the UQI exists and both are possible."""
    source = body.get("answered_by", "unknown")
    lines = [
        f"[answered by: {source}]",
        "",
        f"Identity      : {body['identity']}",
        f"Name          : {body.get('agent_name') or '(unnamed)'}",
        f"Role / type   : {body['role']} / {body.get('agent_type')}",
        f"Description   : {body.get('description') or '-'}",
        "",
        f"Lifecycle     : {body['lifecycle_state']}"
        + ("  (retirement requested)" if body.get("retire_requested") else ""),
        f"Process       : {body['process_state']}  pid={body.get('pid')}",
        f"Health        : {HEALTH_LABELS.get(body.get('healthy'), '?')}",
        f"Working       : {_tri(body.get('working'))}",
        f"Current task  : {body.get('current_task') or '(not recorded - the system logs heartbeats, not task spans)'}",
        f"Last heartbeat: {body.get('last_heartbeat_at') or 'never'}"
        + (f"  ({body['heartbeat_age_seconds']}s ago)" if body.get("heartbeat_age_seconds") is not None else ""),
        f"Work via      : {body.get('work_mechanism') or '-'}",
    ]
    for title, key in (
        ("Responsibilities", "responsibilities"),
        ("Allowed", "allowed"),
        ("NOT allowed", "not_allowed"),
        ("Competencies", "competencies"),
    ):
        values = body.get(key) or []
        lines += ["", f"{title}:"] + ([f"  - {v}" for v in values] or ["  (none)"])
    return "\n".join(lines)


def _tri(value) -> str:
    return {True: "yes", False: "no", None: "n/a (dormant)"}.get(value, "?")


def format_intelligence(artifacts: list[dict]) -> str:
    """Stale lenses are listed alongside active ones and never filtered out. A
    lens that expired is the most informative row here - it is the system
    having noticed something - and a panel showing only what still looks fine
    would be worse than no panel."""
    if not artifacts:
        return "(no intelligence artifacts)"
    blocks = []
    for artifact in artifacts:
        performance = artifact.get("performance") or {}
        block = [
            f"{artifact['name']}  v{artifact['version']}  [{artifact['status'].upper()}]",
            f"  value      : {artifact['value']}",
            f"  graded     : {performance.get('graded_reports', 0)} report(s)"
            f"   mean {_num(performance.get('mean_overall_score'))}"
            f"   worth-the-compute {_num(performance.get('worth_the_compute_rate'))}",
        ]
        observed = artifact.get("observed_under_regime")
        if observed:
            block.append(
                f"  bound under: mean_iv {observed['mean_iv']:.4f}, "
                f"dispersion {observed['iv_dispersion']:.4f}  at {artifact.get('regime_bound_at')}"
            )
        else:
            block.append("  bound under: not yet - a lens earns its regime baseline by performing acceptably")
        if artifact.get("staleness_reason"):
            block.append(f"  STALE      : {artifact['staleness_reason']}")
        block.append(f"  rationale  : {artifact.get('rationale') or '-'}")
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


def _num(value) -> str:
    return "-" if value is None else f"{value:.3f}"


def format_regime(body: dict) -> str:
    market = body.get("market_wide") or {}
    if not market.get("observation_count"):
        return "(no market observations yet)"
    lines = [
        "Market-wide estimate, inferred from observation - the system is never told the regime:",
        f"  mean IV      : {market['mean_iv']:.4f}",
        f"  dispersion   : {market['iv_dispersion']:.4f}",
        f"  observations : {market['observation_count']} across {market['securities']} securities",
        "",
        "Per security:",
        "  {:<10} {:>10} {:>12} {:>7}".format("security", "mean_iv", "dispersion", "obs"),
    ]
    for row in body.get("securities", []):
        lines.append("  {:<10} {:>10.4f} {:>12.4f} {:>7}".format(
            row["security"], row["mean_iv"], row["iv_dispersion"], row["observation_count"]
        ))
    return "\n".join(lines)


def format_cross_checks(rows: list[dict]) -> str:
    """Two findings, side by side, with no verdict line.

    This layout is the point of the whole feature. Neither discovery agent
    judged whether the findings agree, so the panel must not either - adding a
    computed "AGREES"/"DISAGREES" banner here would resolve upstream, in a
    display layer, the exact question addendum 12 §14 reserves for Analysis.
    The reader does the comparing, which is what preserved disagreement means."""
    if not rows:
        return "(no cross-checks yet)"
    blocks = []
    for row in rows:
        block = [
            f"#{row['id']}  {row['security']}  {row['requester_role']} -> {row['responder_role']}"
            f"  [{row['status']} / {row['outcome'] or 'pending'}]",
            f"  Q: {row['question']}",
            f"  {row['requester_role']:>10} claims: {_finding(row['requester_finding'])}",
            f"  {row['responder_role']:>10} claims: {_finding(row['responder_finding'])}",
        ]
        if row["outcome"] == "unanswered":
            block.append("  (nobody answered - uncorroborated, which is not the same as contradicted)")
        elif row["outcome"] == "no_evidence":
            block.append("  (responder looked and found nothing - a real finding, not silence)")
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


def _finding(finding) -> str:
    if finding is None:
        return "(no answer yet)"
    if isinstance(finding, str):
        try:
            finding = json.loads(finding)
        except json.JSONDecodeError:
            return finding
    return ", ".join(f"{k}={v}" for k, v in finding.items())


def format_uqi_exchange(body: dict) -> str:
    """One question and its answer.

    The source line is not decoration. A UQI answer comes from the agent's own
    running process and a /admin/agents read does not, and once both are on
    screen the operator must be able to tell which they are looking at. The pid
    is printed for the same reason - it is the evidence that a live process
    replied."""
    status = body.get("status")
    lines = [f"Q ({body.get('asked_by', '?')} -> {body.get('target_identity')}): {body.get('question')}", ""]

    if status == "pending":
        lines.append("(waiting - the agent answers on its own cycle)")
    elif status == "unanswered":
        lines.append(
            "(no answer - the agent did not service its loop before the timeout. A dormant or "
            "crashed agent cannot answer, and that silence is the diagnostic result, not a fault "
            "in the interface.)"
        )
    else:
        lines.append(f"A [answered by: agent, pid {body.get('answered_by_pid')}]:")
        lines.append("")
        lines.append(body.get("answer") or "")
    return "\n".join(lines)


def format_directives(body: dict) -> str:
    """Every lifecycle action, who asked, and what the Controller made of it.

    Requester is shown on every line because it is the interesting column: the
    panel, COO, and any future requester all file into the same queue, and the
    Controller executes all of them. Reading this log is how you see that the
    operator restored an agent's standing while COO separately decided to staff
    it - three authorities, one audit trail."""
    pending = body.get("pending", [])
    completed = body.get("completed", [])
    lines = [f"Pending ({len(pending)}):"]
    lines += [
        f"  #{d['id']:<4} {d['directive_type']:<7} {(d['target_identity'] or d['target_role'] or ''):<13}"
        f" by {d['requested_by']:<9} {d['reason'] or ''}"
        for d in pending
    ] or ["  (none)"]

    lines += ["", f"Completed ({len(completed)}), newest first:"]
    lines += [
        f"  #{d['id']:<4} {d['directive_type']:<7} {(d['target_identity'] or d['target_role'] or ''):<13}"
        f" by {d['requested_by']:<9} -> {d['outcome']:<8} {d['reason'] or ''}"
        for d in completed
    ] or ["  (none)"]
    return "\n".join(lines)


def format_discovery(body: dict) -> str:
    pending = body.get("pending_reports", [])
    analyses = body.get("recent_analyses", [])
    lines = [f"Pending report queue ({len(pending)}), in the order Analysis will take them:"]
    lines += [
        f"  {n}. #{r['id']} {r['security']:<6} from {r['producer_identity']:<13} "
        f"waited {r.get('waiting_seconds', 0):>6.1f}s  -- {r.get('triage_reason', '')}"
        for n, r in enumerate(pending, start=1)
    ] or ["  (empty)"]

    lines += ["", f"Recent analyses ({len(analyses)}):"]
    for result in analyses:
        graded = result.get("overall_score")
        lines += [
            f"  {result['security']:<6} confidence {result['confidence']:.2f}"
            f"   graded {'-' if graded is None else f'{graded:.2f}'}"
            f"   worth-the-compute {_worth(result.get('worth_the_compute'))}",
            f"    {(result.get('thesis') or '')[:160]}",
        ]
    if not analyses:
        lines.append("  (none yet)")
    return "\n".join(lines)


def _worth(value) -> str:
    return "-" if value is None else ("yes" if value else "no")
