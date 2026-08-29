"""    python -m demonstration report     what can and cannot be shown, without running
    python -m demonstration run        the demonstration itself
    python -m demonstration acts       the sequence, and how long it will take

`report` exists as its own command because the specification requires a
current-capability report *before* a demo, and because the honest answer to "what
can this system do" should not cost ten minutes of runtime to obtain.
"""

from __future__ import annotations

import argparse
import json
import sys

from demonstration import capabilities as registry
from demonstration.engine import FULL_DEMO, Demonstration


def _rule(title: str) -> str:
    return f"\n{title}\n" + "-" * len(title)


def cmd_report(args) -> int:
    report = Demonstration.capability_report()
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(_rule("CURRENT CAPABILITY REPORT"))
    print(f"code       {report['code_version']}")
    print(f"data mode  synthetic - every price in this system is generated (§113)")
    print(f"roles      {len(report['roles_implemented'])} implemented: "
          f"{', '.join(report['roles_implemented'])}")
    print(f"stores     {len(report['stores_governed'])} under the migration engine")
    print(f"scenarios  {len(report['scenarios_available'])} in the library")

    print(_rule(f"CAN BE DEMONSTRATED ({len(report['demonstrable'])})"))
    for cap in report["demonstrable"]:
        where = cap["scenario"] or "composed from more than one run"
        print(f"  {cap['id']:20} {cap['name']}")
        print(f"  {'':20} via {where}")
        print(f"  {'':20} evidence: {cap['evidence']}")

    print(_rule(f"NOT IMPLEMENTED ({len(report['absent'])})"))
    print("  The specification asks a demo to show these. They do not exist, and the")
    print("  demo will not pretend otherwise.\n")
    for absent in report["absent"]:
        print(f"  {absent['id']:20} {absent['name']}")
        print(f"  {'':20} {absent['why']}")

    print(_rule("CLIENT-FACING"))
    safe = [c for c in report["demonstrable"] if c["client_safe"]]
    print(f"  {len(safe)} of {len(report['demonstrable'])} capabilities are marked "
          "client-safe.")
    print("  Nothing is, deliberately: no external client has been onboarded and the")
    print("  presentation boundary has never been tested. Marking something safe is a")
    print("  decision somebody makes, not a default.")
    return 0


def cmd_acts(args) -> int:
    from simulation import scenario as scenario_module

    scenarios = scenario_module.load_all()
    total = 0.0
    print(_rule("THE DEMONSTRATION"))
    for i, act in enumerate(FULL_DEMO, start=1):
        if act.scenario and act.scenario in scenarios:
            seconds = scenarios[act.scenario].duration_seconds
            total += seconds
            extra = "  (restarted from the previous run)" if act.inherit_from_previous else ""
            print(f"  {i}. {act.title}\n     {act.scenario}, {seconds:.0f}s{extra}")
        else:
            print(f"  {i}. {act.title}\n     read from the previous run, no extra time")
    print(f"\n  {total:.0f}s of scenario time, plus roughly 20s of startup per run.")
    return 0


def cmd_run(args) -> int:
    demo = Demonstration(mode=args.mode)
    print(_rule("CAPABILITY REPORT (before the demo, as the specification requires)"))
    report = Demonstration.capability_report()
    print(f"  {len(report['demonstrable'])} capabilities can be demonstrated; "
          f"{len(report['absent'])} the specification asks for do not exist.")
    print("  Run `python -m demonstration report` for the detail.")

    summary = demo.run()

    print(_rule("EXECUTIVE SUMMARY"))
    shown = summary["capabilities_shown"]
    missed = summary["capabilities_not_observed"]
    print(f"  demo        {summary['demo_id']}")
    print(f"  code        {summary['code_version']}")
    print(f"  data        {summary['data_mode']} - no real price was used, because none exists")
    print(f"  shown       {len(shown)} of {len(summary['acts'])} acts: {', '.join(shown)}")
    if missed:
        print(f"  NOT SHOWN   {', '.join(missed)}")
    print(f"\n  Not implemented, and therefore not demonstrated ({len(summary['not_implemented'])}):")
    for absent in summary["not_implemented"]:
        print(f"    - {absent['name']}")
    print("\n  Runs, for anyone who wants to check rather than take this on trust:")
    for capability, directory in summary["runs"].items():
        print(f"    {capability:20} {directory}")

    if args.out:
        from demonstration.engine import write_summary
        path = write_summary(summary, args.out)
        print(f"\n  summary written to {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m demonstration")
    sub = parser.add_subparsers(dest="command", required=True)

    report = sub.add_parser("report", help="what can and cannot be shown, without running")
    report.add_argument("--json", action="store_true")
    report.set_defaults(func=cmd_report)

    acts = sub.add_parser("acts", help="the sequence and how long it takes")
    acts.set_defaults(func=cmd_acts)

    run = sub.add_parser("run", help="run the demonstration")
    run.add_argument("--mode", default="full")
    run.add_argument("--out", help="write the summary as JSON to this path")
    run.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
