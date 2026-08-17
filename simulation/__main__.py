"""CLI: `python -m simulation list` and `python -m simulation run <scenario-id>`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from simulation import harness, scenario as scenario_module


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

    print(f"running {scenario.id} v{scenario.version} for {scenario.duration_seconds:.0f}s")
    result = harness.execute(scenario)

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
    print(f"\n-- {summary['scenario_id']} v{summary['scenario_version']} ({model}) --")
    print(f"  detections {pipeline['detector_events']:<6} evidence {pipeline['evidence_items']:<7} "
          f"reports {pipeline['reports_filed']:<5} analyses {pipeline['analyses']:<5} "
          f"grades {pipeline['grades']}")
    print(f"  queue      arrivals {queue['arrivals']}, completed {queue['completions']}, "
          f"peak depth {queue['max_depth']}, final {queue['final_depth']}"
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m simulation")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show the scenario library").set_defaults(func=_cmd_list)

    run_parser = sub.add_parser("run", help="execute one scenario")
    run_parser.add_argument("scenario_id")
    run_parser.add_argument("--force", action="store_true",
                            help="run a scenario whose lifecycle state says it should not be run")
    run_parser.set_defaults(func=_cmd_run)

    summarise_parser = sub.add_parser(
        "summarise", help="re-read a finished run directory and rewrite its summary")
    summarise_parser.add_argument("directory", help="a run directory, or a run_id under simulation/runs")
    summarise_parser.add_argument("-v", "--verbose", action="store_true", help="dump every metric")
    summarise_parser.set_defaults(func=_cmd_summarise)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
