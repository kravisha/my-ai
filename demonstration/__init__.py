"""The Demonstration Engine: shows what this system can actually do, right now.

Separate from the Simulation Engine on purpose, and the specification is explicit
about the split - the Simulation Engine creates the world, the Demonstration
Engine orchestrates a demonstration in it. So this package sits *above*
`simulation/` and drives it, and it owns no world-generation logic of its own.

It also owns no results. Every number in a demo report is read back out of the
run's own database by machinery that already existed, because the demo's whole
claim is that it shows the real system rather than a retelling of it.

Entry point:

    python -m demonstration report        # what can and cannot be shown, no run
    python -m demonstration run           # the demonstration
"""
