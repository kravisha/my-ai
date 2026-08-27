"""CLI: `python -m simulation list` and `python -m simulation run <scenario-id>`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from simulation import harness, parity_diagnosis, parity_evaluation, parity_world, scenario as scenario_module, stage1, verification


def _cmd_list(args) -> int:
    scenarios = scenario_module.load_all()
    if not scenarios:
        print("no scenarios found")
        return 1
    width = max(len(s) for s in scenarios)
    for scenario_id, scenario in sorted(scenarios.items()):
        marker = " " if scenario.is_runnable else "-"
        print(f"{marker} {scenario_id.ljust(width)}  v{scenario.version}  {scenario.lifecycle:<10} "
              f"{scenario.duration_seconds:>6.0f}s")
    print("\n(a leading '-' marks a scenario that is not runnable in its current lifecycle state)")
    return 0


def _cmd_run(args) -> int:
    scenarios = scenario_module.load_all()
    scenario = scenarios.get(args.scenario_id)
    if scenario is None:
        print(f"no scenario {args.scenario_id!r}. Known: {', '.join(sorted(scenarios))}", file=sys.stderr)
        return 2
    if not scenario.is_runnable and not args.force:
        print(
            f"scenario {scenario.id!r} is {scenario.lifecycle!r} and will not be run. Use --force to "
            "run it anyway; the manifest records the lifecycle state either way.",
            file=sys.stderr,
        )
        return 2

    inherit = _resolve_inheritance(args.inherit, scenario.id)
    if args.inherit and inherit is None:
        print(f"nothing to inherit from for {scenario.id!r}", file=sys.stderr)
        return 2

    print(f"running {scenario.id} v{scenario.version} for {scenario.duration_seconds:.0f}s"
          + (f", inheriting {inherit.name}" if inherit else ""))
    result = harness.execute(scenario, inherit_from=inherit)

    print(f"\nrun_id     {result.run_id}")
    print(f"directory  {result.directory}")
    if result.ready_after_seconds is not None:
        print(f"ready in   {result.ready_after_seconds:.1f}s")
    print(f"shutdown   {'clean' if result.graceful else 'NOT CLEAN'} - {result.shutdown_detail}")

    if result.summary:
        _print_summary(result.summary)

    # A non-clean shutdown fails the command even though the run itself may have
    # produced usable data, because the next run inherits the consequences: an
    # agent process left alive keeps writing, and results from an organization
    # nobody is watching are worse than no results.
    return 0 if result.graceful and result.properties_passed else 1


def _resolve_inheritance(value: str | None, scenario_id: str) -> Path | None:
    if not value:
        return None
    if value == "latest":
        return harness.latest_run(scenario_id)
    candidate = Path(value)
    return candidate if candidate.exists() else harness.RUNS_DIR / value


def _cmd_chain(args) -> int:
    """Run one scenario repeatedly, each generation starting from the last one's database.

    The point is day two. Every run the harness produced before this started from
    an empty database, so an entire class of defect - anything that only appears
    against state that already exists - was structurally unreachable. A chain is
    what makes accumulated regime observations, an inherited report backlog, a
    partly-consumed name pool and a migrated schema part of the experiment
    instead of things production discovers alone."""
    scenarios = scenario_module.load_all()
    scenario = scenarios.get(args.scenario_id)
    if scenario is None:
        print(f"no scenario {args.scenario_id!r}", file=sys.stderr)
        return 2

    inherit = _resolve_inheritance(args.inherit, scenario.id)
    failures = 0
    for generation in range(1, args.generations + 1):
        print(f"\n=== generation {generation}/{args.generations} "
              f"({'fresh' if inherit is None else 'inheriting ' + inherit.name}) ===")
        result = harness.execute(scenario, inherit_from=inherit)
        print(f"run_id     {result.run_id}")
        print(f"shutdown   {'clean' if result.graceful else 'NOT CLEAN'} - {result.shutdown_detail}")
        if result.summary:
            _print_summary(result.summary)
        if not (result.graceful and result.properties_passed):
            failures += 1
        inherit = result.directory

    print(f"\n{args.generations - failures}/{args.generations} generations passed")
    return 0 if failures == 0 else 1


def _cmd_summarise(args) -> int:
    directory = Path(args.directory)
    if not directory.exists():
        candidate = harness.RUNS_DIR / args.directory
        if not candidate.exists():
            print(f"no run directory at {directory} or {candidate}", file=sys.stderr)
            return 2
        directory = candidate

    summary = harness.summarise_run(directory)
    _print_summary(summary, verbose=args.verbose)
    return 0 if summary["properties"]["failed"] == 0 else 1


def _print_summary(summary: dict, verbose: bool = False) -> None:
    metrics = summary["metrics"]
    pipeline, queue, cross = metrics["pipeline"], metrics["queue"], metrics["cross_check"]
    population, intel = metrics["population"], metrics["intelligence"]

    model = "live model" if summary.get("model_available") else "NO MODEL - Analysis degraded"
    generation = summary.get("generation") or 1
    lineage = f", generation {generation}" if generation > 1 else ""
    print(f"\n-- {summary['scenario_id']} v{summary['scenario_version']} ({model}{lineage}) --")
    print(f"  detections {pipeline['detector_events']:<6} evidence {pipeline['evidence_items']:<7} "
          f"reports {pipeline['reports_filed']:<5} analyses {pipeline['analyses']:<5} "
          f"grades {pipeline['grades']}")
    print(f"  queue      arrivals {queue['arrivals']}, completed {queue['completions']}, "
          f"peak {queue['max_depth']}, net {queue['net_depth_change']:+d}, "
          f"pending at end {queue['pending_at_end']}"
          + (f" (inherited {queue['inherited_backlog']})" if queue.get("inherited_backlog") else "")
          + (f", pressure x{queue['pressure_ratio']}" if queue["pressure_ratio"] else ""))
    if pipeline["handling_latency_seconds"]["p50"] is not None:
        latency = pipeline["handling_latency_seconds"]
        print(f"  latency    p50 {latency['p50']}s  p90 {latency['p90']}s  max {latency['max']}s")
    print(f"  crosscheck {cross['total']} total, unanswered rate {cross['unanswered_rate']}, "
          f"{cross['open_at_end']} open at end")
    print(f"  population {population['registered']} registered, {population['respawns']} respawns, "
          f"{len(population['running_at_end'])} still running, "
          f"{population['failed_directives']} failed directives")
    print(f"  intel      {intel['active']} active / {intel['stale']} stale lenses, "
          f"{len(intel['regime_bound'])} regime-bound, "
          f"{intel['regime_observations']} regime observations")

    if verbose:
        print(json.dumps(metrics, indent=2))

    properties = summary["properties"]
    if not properties["asserted"]:
        print("\n  properties: NONE DECLARED - this run asserted nothing")
        return
    print(f"\n  properties: {properties['passed']}/{properties['total']} passed")
    for result in summary["property_results"]:
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"    [{mark}] {result['name']}: {result['detail']}")


def _cmd_stage1(args) -> int:
    """Sample `args.worlds` Monte Carlo worlds from `args.seed`, run each
    through the real harness, and score against the precomputed answer key."""
    summary = stage1.run_exercise(
        master_seed=args.seed, count=args.worlds, duration_seconds=args.duration,
    )

    for entry in summary["worlds"]:
        counts = entry["score"]["counts"]
        status = "graceful" if entry["graceful"] else "NOT CLEAN"
        print(
            f"world {entry['world']['index']:>2} (run {entry['run_id']}, {status}): "
            f"hits {counts['hit']} misses {counts['miss']} beyond_lens {counts['beyond_lens']} "
            f"artifact_detections {counts['artifact_detection']} "
            f"false_positives {counts['false_positive']} clean {counts['clean']}"
        )

    agg = summary["aggregate_counts"]
    rate = summary["overall_detection_rate"]
    rate_str = f"{rate:.3f}" if rate is not None else "n/a (no detectable plants)"
    print(
        f"\naggregate: hits {agg['hit']} misses {agg['miss']} beyond_lens {agg['beyond_lens']} "
        f"artifact_detections {agg['artifact_detection']} false_positives {agg['false_positive']} "
        f"clean {agg['clean']}"
    )
    print(f"detection rate: {rate_str}")
    print(f"summary written to {summary['summary_path']}")

    return 0 if all(entry["graceful"] for entry in summary["worlds"]) else 1


def _cmd_parity(args) -> int:
    """The Market Data Simulation Engine's Version 1 mission (addendum 25):
    put-call parity training worlds, refusing outright if reference data
    is not READY (fail closed, addendum 25 SS3, visibly rather than silently).

    --store switches from the simulator's own answer-key run to the mission
    runner's other entry point: build the world and store it into the Data
    Store against --db, for Explorer/Speculator/Analysis to consume as the
    real detector (parity_world.store_world's docstring)."""
    from backend import fi_db

    db_path = Path(args.db) if args.db else fi_db.DB_PATH
    conn = fi_db.get_connection(db_path)
    try:
        fi_db.init_schema(conn)
        config = parity_world.MissionConfig(
            mission_id=f"parity-cli-{args.seed}",
            run_mode="simulation",
            strategy="put_call_parity_arbitrage",
            seed=args.seed,
            n_scenarios=args.scenarios,
        )
        if args.store:
            try:
                result = parity_world.store_world(conn, config)
            except parity_world.ReferenceNotReady as exc:
                print(f"REFUSED: {exc}", file=sys.stderr)
                return 2
            print(f"stored {result['stored']['kept']} observation(s) "
                  f"({result['stored']['already_held']} already held) across {result['scenarios']} scenario(s)")
            print(f"summary written to {result['summary_path']}")
            return 0
        try:
            report = parity_world.run_parity_exercise(conn, config)
        except parity_world.ReferenceNotReady as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 2
    finally:
        conn.close()

    print(f"{'scenario':<24} {'variant':<16} {'symbol':<8} outcome")
    for entry in report["scenarios"]:
        gt = entry["ground_truth"]
        print(f"{entry['scenario_id']:<24} {gt['variant']:<16} {gt['symbol']:<8} {entry['outcome']}")

    m = report["metrics"]
    rate = f"{m['pass_rate']:.3f}" if m["pass_rate"] is not None else "n/a"
    print(
        f"\nassets_simulated={m['assets_simulated']} contracts_generated={m['contracts_generated']} "
        f"opportunities_injected={m['opportunities_injected']} chatter_items={m['chatter_items']}"
    )
    print(
        f"detected={m['detected']} missed={m['missed']} false_positives={m['false_positives']} "
        f"pass_rate={rate} strategy_exercised={m['strategy_exercised']}"
    )
    print(f"final state: {report['states'][-1]}")
    print(f"summary written to {report['summary_path']}")

    return 0 if report["states"][-1] == parity_world.COMPLETED else 1


def _cmd_parity_evaluate(args) -> int:
    """The Evaluator's own CLI entry point (simulation/parity_evaluation.py):
    grade a stored mission's ground-truth summary against what the
    organization's own records (parity_events, discovery_reports,
    analysis_results) show it actually did.

    Exit code 0 iff strategy_exercised - addendum 25 SS18's requirement that
    a run which never exercised the selected strategy cannot certify as a
    successful training run, made visible to a caller's script rather than
    only to a human reading the printed table."""
    from backend import fi_db

    db_path = Path(args.db) if args.db else fi_db.DB_PATH
    conn = fi_db.get_connection(db_path)
    try:
        evaluation = parity_evaluation.evaluate_mission(conn, args.summary_path)
    finally:
        conn.close()

    print(f"{'scenario':<24} {'variant':<16} {'symbol':<8} {'outcome':<12} reasons")
    for entry in evaluation["scenarios"]:
        reasons = ", ".join(entry["reasons"])
        print(f"{entry['scenario_id']:<24} {entry['variant']:<16} {entry['symbol']:<8} {entry['outcome']:<12} {reasons}")

    m = evaluation["metrics"]
    rate = f"{m['pass_rate']:.3f}" if m["pass_rate"] is not None else "n/a"
    by_outcome = m["by_outcome"]
    print(
        f"\nPASS={by_outcome['PASS']} PARTIAL={by_outcome['PARTIAL']} FAIL={by_outcome['FAIL']} "
        f"INCONCLUSIVE={by_outcome['INCONCLUSIVE']} pass_rate={rate}"
    )
    print(
        f"genuine_detected={m['genuine_detected']} genuine_missed={m['genuine_missed']} "
        f"false_positives={m['false_positives']} strategy_exercised={m['strategy_exercised']} "
        f"retry_required={m['retry_required']}"
    )
    print(f"evaluation written to {evaluation['evaluation_path']}")

    return 0 if m["strategy_exercised"] else 1


def _cmd_parity_diagnose(args) -> int:
    """The diagnosis stage's own CLI entry point (simulation/parity_diagnosis.py,
    addendum 25 §19): walk the differential for every non-PASS scenario in an
    evaluation, print what it found, and say whether a rerun is worth it.

    Exit code 0 when the mission is certified complete or the only causes in
    play are in_flight (the run needs time, not a rerun); 2 when a retry is
    recommended - mirroring parity-evaluate's exit-code convention of making
    the verdict visible to a caller's script, not only to a human reading the
    printed table."""
    from backend import fi_db

    db_path = Path(args.db) if args.db else fi_db.DB_PATH
    conn = fi_db.get_connection(db_path)
    try:
        diagnosis = parity_diagnosis.diagnose_mission(conn, args.evaluation_path)
    finally:
        conn.close()

    print(f"{'scenario':<24} {'variant':<16} {'outcome':<12} {'component':<18} causes")
    for entry in diagnosis["scenarios"]:
        causes = ", ".join(entry["causes"]) or "(none)"
        print(f"{entry['scenario_id']:<24} {entry['variant']:<16} {entry['outcome']:<12} {entry['component']:<18} {causes}")

    if diagnosis["corrective_items"]:
        print("\ncorrective items:")
        for item in diagnosis["corrective_items"]:
            print(f"  [{item['classification']:<10}] {item['cause']} ({len(item['scenarios'])} scenario(s): "
                  f"{', '.join(item['scenarios'])})")
            print(f"               {item['remedy']}")
    else:
        print("\nno corrective items")

    if diagnosis["mission_certified_complete"]:
        print("\nVERDICT: mission certified complete - every scenario PASS")
    elif diagnosis["retry_recommended"]:
        guidance = diagnosis["retry_guidance"]
        print(f"\nVERDICT: retry recommended - {guidance['reason']}")
        print(f"         rerun_same_seed={guidance['rerun_same_seed']} adjust_world_first={guidance['adjust_world_first']}")
    elif diagnosis["wait_and_reevaluate"]:
        print(f"\nVERDICT: wait and re-evaluate - {diagnosis['retry_guidance']['reason']}")
    else:
        print(f"\nVERDICT: {diagnosis['retry_guidance']['reason']}")

    print(f"\ndiagnosis written to {diagnosis['diagnosis_path']}")

    # certified-complete and "nothing but in_flight" both leave
    # retry_recommended False (in_flight causes are excluded from it by
    # construction), so this one check covers both 0-exit cases at once.
    return 2 if diagnosis["retry_recommended"] else 0


def _cmd_verify(args) -> int:
    """Everything, and one answer (TQ-91, §129).

    The two simulation systems have always been runnable and never together, so
    "does the organization work" had two answers depending on which somebody had
    run. This is the one place that asks both and says so in a single line.

    **A scenario that did not run is not a scenario that passed.** The verdict
    has three values for that reason: INCOMPLETE is what an honest verifier says
    when nothing failed and not everything was asked.
    """
    scenarios = scenario_module.load_all()
    chosen = args.scenarios.split(",") if args.scenarios else sorted(
        sid for sid, s in scenarios.items() if s.is_runnable)
    minutes = sum(scenarios[sid].duration_seconds for sid in chosen if sid in scenarios) / 60

    print(f"verifying {len(chosen)} scenario(s)"
          + ("" if args.no_curriculum else " and the curriculum"))
    print(f"expect roughly {minutes:.0f} minutes of running, plus startup per scenario\n")

    def progress(kind, name, duration):
        print(f"  {kind:<10} {name}" + (f"  ({duration:.0f}s)" if duration else ""), flush=True)

    result = verification.verify(
        scenario_ids=chosen, include_curriculum=not args.no_curriculum,
        on_progress=progress)
    _print_verification(result)
    return 0 if result.verdict == verification.VERDICT_PASS else 1


def _print_verification(result) -> None:
    print("\n" + "=" * 78)
    print("SCENARIOS")
    for entry in result.scenarios:
        mark = "ok  " if entry["passed"] else "FAIL"
        detail = f"{entry['properties_passed']}/{entry['properties_total']} properties"
        if not entry["graceful"]:
            detail += ", SHUTDOWN NOT CLEAN"
        print(f"  [{mark}] {entry['id']:<24} {detail}")
        for failure in entry["failures"]:
            print(f"           - {failure}")
    if not result.scenarios:
        print("  none run")

    for skipped in result.skipped:
        # Listed under their own heading rather than mixed with results, because
        # a skipped scenario in a list of passes reads as a pass.
        print(f"  [skip] {skipped['id']:<24} {skipped['why']}")

    print("\nCURRICULUM")
    if result.curriculum is None:
        print("  not run")
    else:
        c = result.curriculum
        mark = "ok  " if c["passed"] else "FAIL"
        print(f"  [{mark}] {c['curriculum']} v{c['version']}: {c['exercises']} exercises")
        for failure in c["failures"]:
            print(f"           - failed: {failure}")
        for regression in c["regressions"]:
            print(f"           - REGRESSION: {regression}")
        for stale in c["out_of_date"]:
            print(f"           - curriculum out of date: {stale} passed and was not expected to")

    print("\nNOT COVERED BY ANY OF THIS")
    for gap in verification.NOT_COVERED:
        print(f"  - {gap}")

    print("\n" + "=" * 78)
    print(f"VERDICT  {result.verdict}")
    if result.verdict == verification.VERDICT_INCOMPLETE:
        print("         Nothing failed, and not everything was asked. A skipped scenario")
        print("         is not a passing one.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m simulation")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show the scenario library").set_defaults(func=_cmd_list)

    verify_parser = sub.add_parser(
        "verify", help="run every scenario and the curriculum, and give one verdict")
    verify_parser.add_argument(
        "--scenarios", help="comma-separated ids; default is every runnable scenario")
    verify_parser.add_argument(
        "--no-curriculum", action="store_true",
        help="scenarios only. The verdict is INCOMPLETE, never PASS.")
    verify_parser.set_defaults(func=_cmd_verify)

    run_parser = sub.add_parser("run", help="execute one scenario")
    run_parser.add_argument("scenario_id")
    run_parser.add_argument("--force", action="store_true",
                            help="run a scenario whose lifecycle state says it should not be run")
    run_parser.add_argument("--inherit", metavar="RUN",
                            help="start from another run's database: a run_id, a path, or 'latest'")
    run_parser.set_defaults(func=_cmd_run)

    chain_parser = sub.add_parser(
        "chain", help="run a scenario several times, each starting from the previous database")
    chain_parser.add_argument("scenario_id")
    chain_parser.add_argument("-n", "--generations", type=int, default=3)
    chain_parser.add_argument("--inherit", metavar="RUN",
                              help="seed the first generation from an existing run instead of empty")
    chain_parser.set_defaults(func=_cmd_chain)

    summarise_parser = sub.add_parser(
        "summarise", help="re-read a finished run directory and rewrite its summary")
    summarise_parser.add_argument("directory", help="a run directory, or a run_id under simulation/runs")
    summarise_parser.add_argument("-v", "--verbose", action="store_true", help="dump every metric")
    summarise_parser.set_defaults(func=_cmd_summarise)

    stage1_parser = sub.add_parser(
        "stage1", help="Monte Carlo Stage 1 training exercise: sample worlds, run, score")
    stage1_parser.add_argument("--worlds", type=int, default=3, help="how many worlds to sample")
    stage1_parser.add_argument("--seed", type=int, required=True, help="master seed for the draw")
    stage1_parser.add_argument("--duration", type=float, default=45.0, help="seconds per world's run")
    stage1_parser.set_defaults(func=_cmd_stage1)

    parity_parser = sub.add_parser(
        "parity", help="Market Data Simulation Engine: put-call parity arbitrage mission (addendum 25)")
    parity_parser.add_argument("--seed", type=int, required=True, help="mission seed")
    parity_parser.add_argument("--scenarios", type=int, default=12, help="how many scenarios to generate")
    parity_parser.add_argument("--db", metavar="PATH", default=None,
                               help="financial_intelligence.db path (default: FI_DB_PATH / the repo's own db)")
    parity_parser.add_argument("--store", action="store_true",
                               help="store the mission's world into the Data Store against --db for the real "
                                    "agents to consume, instead of running the simulator's own answer key")
    parity_parser.set_defaults(func=_cmd_parity)

    parity_evaluate_parser = sub.add_parser(
        "parity-evaluate",
        help="grade a stored parity mission's ground-truth summary against the org's own records (addendum 25 SS16)")
    parity_evaluate_parser.add_argument("summary_path", help="path to a parity-<mission>-<ts>.json summary")
    parity_evaluate_parser.add_argument("--db", metavar="PATH", default=None,
                                        help="financial_intelligence.db path (default: FI_DB_PATH / the repo's own db)")
    parity_evaluate_parser.set_defaults(func=_cmd_parity_evaluate)

    parity_diagnose_parser = sub.add_parser(
        "parity-diagnose",
        help="diagnose a graded parity mission's non-PASS scenarios against the offline detector (addendum 25 SS19)")
    parity_diagnose_parser.add_argument("evaluation_path", help="path to a parity-<mission>-<ts>.evaluation.json file")
    parity_diagnose_parser.add_argument("--db", metavar="PATH", default=None,
                                        help="financial_intelligence.db path (default: FI_DB_PATH / the repo's own db)")
    parity_diagnose_parser.set_defaults(func=_cmd_parity_diagnose)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
