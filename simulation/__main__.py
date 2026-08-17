"""CLI: `python -m simulation list` and `python -m simulation run <scenario-id>`."""

from __future__ import annotations

import argparse
import sys

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

    # A non-clean shutdown fails the command even though the run itself may have
    # produced usable data, because the next run inherits the consequences: an
    # agent process left alive keeps writing, and results from an organization
    # nobody is watching are worse than no results.
    return 0 if result.graceful else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m simulation")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show the scenario library").set_defaults(func=_cmd_list)

    run_parser = sub.add_parser("run", help="execute one scenario")
    run_parser.add_argument("scenario_id")
    run_parser.add_argument("--force", action="store_true",
                            help="run a scenario whose lifecycle state says it should not be run")
    run_parser.set_defaults(func=_cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
