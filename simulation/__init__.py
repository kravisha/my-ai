"""Runs the real organization under chosen conditions, in an isolated database.

Not a test harness for components - `tests/` already does that, and the defects
this exists to find are precisely the ones a component test cannot express:
timing constants set below the rate they govern, fixtures incapable of producing
the phenomenon they feed, lifecycle races between real OS processes, and schema
defects that only appear against an already-migrated database.

Entry point: `python -m simulation run <scenario-id>`.
"""
