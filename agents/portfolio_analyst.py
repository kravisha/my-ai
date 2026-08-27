"""Portfolio Analyst: the on-demand role addendum 9 specifies and nobody built
(TASK_QUEUE TQ-79; addendum 9 §2, §3; docs/SPEC_RECONCILIATION.md §112, §115).

Addendum 9 §2, canonical since August 2026:

> *"A client explicitly requests portfolio analysis and supplies portfolio
> information. The request reaches the backend. The COO directs the coordinator
> to create or allocate a Portfolio Analyst process. The Portfolio Analyst
> combines the supplied portfolio information into a unified analytical view. It
> performs the requested analysis… It returns a client-facing report."*

`docs/README.md` has recorded this role as *"Not built"* since the addendum-12
gap analysis. Everything it needs now exists: the provider interface fetches
(§111), `backend/consolidation.py` combines several sources into one view
(TQ-78), and `holdings.concentration` analyses whatever it is handed (§101).

## It works only when tasked

§115: *"The portfolio analyst agent does work only when tasked. The request has
to come from the client."* There is no idle analyst reaching for portfolios to
look at, which is a different shape from every other agent here — Explorer and
Speculator go looking, and Analysis consumes a queue the organization fills.
This one consumes a queue **a client** fills, and produces nothing when it is
empty.

That difference is worth stating because it changes what a quiet cycle means. An
Explorer that finds nothing may be broken. An analyst that finds nothing to do is
working correctly, and any starvation or health check that treated the two the
same would be wrong about this one.

## It retains nothing, and the loop is where that is true or not

The positions this agent fetches exist in one local variable for the length of
one cycle. They are consolidated, analysed, turned into a report, and the report
goes back through `backend/analysis_requests.py` — which deletes it when the
client collects it (§111, §115).

**Nothing in this file writes a position anywhere**, and the test that matters
asserts it as a property of the filesystem and the schema rather than by reading
the code.

## A partial answer is an answer

A client with three brokers and one outage is entitled to the two that answered,
**provided they are told what they are looking at**. So a source that fails is
carried into the consolidation as a failure (TQ-78) and the report says so; the
request only fails when nothing could be produced at all.

The alternative — refusing the whole analysis because one source was down —
would be the kind of correctness that is useless to the person asking.

Run directly as: python -m agents.portfolio_analyst <identity>
Normally launched by backend/controller.py as a subprocess, not by hand.
"""

import sys

from agents.base import run_agent
from backend import analysis_requests, consolidation, holdings, portfolio_providers

ROLE = "portfolio_analyst"

# What this agent knows how to be asked for. A closed vocabulary, fail-closed on
# an unknown one: an analysis this build cannot perform is not one it may quietly
# substitute something else for.
ANALYSIS_CONCENTRATION = "concentration"
ANALYSES = (ANALYSIS_CONCENTRATION,)


class AnalysisRefused(ValueError):
    """A request this agent will not attempt, with a reason for the client."""


def _fetch(source_descriptor: dict):
    """One source, fetched. Returns a `SourceAnswer`, or a failure to carry.

    A failure is **returned rather than raised** so that one unreachable broker
    does not cost a client the analysis of the others (TQ-78). What is returned
    is the reason, in words that reach the report.

    ## Why it asks the account how much it holds (TQ-80)

    The rows a source sends are not evidence that they are all of them. A broker
    that pages, times out or truncates sends a well-formed answer that is short,
    and until this agent asked, **it had no way to know** — it treated "the
    positions I received" as "all the positions", which is defaulting an absence
    to the favourable value.

    So it asks the account, separately, and hands both to the consolidation. The
    two disagreeing is the signal, and it is the only one available: there is no
    stored history to compare against (§111) and no price to reconcile a total
    against (§113).

    A provider that will not say returns `None`, and that stays **unknown** here
    rather than being read as confirmation."""
    try:
        source = portfolio_providers.Source(**source_descriptor)
    except (TypeError, ValueError) as malformed:
        return f"the source description could not be used ({malformed})"
    try:
        provider = portfolio_providers.for_source(source)
        held = provider.get_holdings(source)
        return consolidation.SourceAnswer(
            holdings=tuple(held), expected_positions=_expected_positions(provider, source))
    except portfolio_providers.ProviderRefused as refused:
        return str(refused)
    except portfolio_providers.ProviderCapabilityUnavailable as unavailable:
        return str(unavailable)
    except Exception as unreachable:  # noqa: BLE001
        # Any other failure is the source's, not this agent's. Carried with its
        # type so a report can say what went wrong without this agent having to
        # anticipate every provider's failure modes.
        return f"the source did not answer ({unreachable.__class__.__name__})"


def _expected_positions(provider, source) -> int | None:
    """What the account says it holds, or None if it will not say.

    A failure to *ask* is unknown rather than fatal: a provider that cannot
    describe its account still gave us positions, and refusing the whole source
    because it could not confirm a count would throw away an answer over a
    missing assurance. `None` carries that honestly."""
    try:
        return provider.position_count(source)
    except Exception:  # noqa: BLE001
        return None


def analyse(request: dict) -> dict:
    """Fetch every source, consolidate, analyse, and build the client's report.

    Separate from the agent loop and taking a plain request, so it can be tested
    without a database, a subprocess or a spawned identity - the same reasoning
    §101 gave for `concentration` taking holdings rather than a connection, and
    it is why the interesting cases here (a source down, two sources disagreeing)
    are reachable at all."""
    requested = request.get("requested") or ANALYSIS_CONCENTRATION
    if requested not in ANALYSES:
        raise AnalysisRefused(
            f"I do not know how to perform {requested!r}. I can do: "
            f"{', '.join(ANALYSES)}.")

    fetched = [(descriptor.get("name") or f"source-{index}", _fetch(descriptor))
               for index, descriptor in enumerate(request["sources"])]
    view = consolidation.consolidate(fetched)

    report = {
        "requested": requested,
        "sources": list(view.sources),
        "as_of": view.as_of,
        "complete": view.complete,
        "failed_sources": [dict(failure) for failure in view.failed_sources],
        # Answered, and short of what the account says it holds (TQ-80). Named
        # separately from a failure because the remedy differs: a failed source
        # can be retried, a short one has already answered and answered wrongly.
        "incomplete_sources": [dict(entry) for entry in view.incomplete_sources],
        # Answered, and would not say how much it holds. Unknown, which is a
        # third thing from complete and from short.
        "unconfirmed_sources": list(view.unconfirmed_sources),
        "conflicts": [dict(conflict) for conflict in view.conflicts],
        "notes": list(view.notes),
        "positions": [
            {"symbol": position.symbol,
             "asset_class": position.asset_class,
             "net_quantity": position.net_quantity,
             "average_cost": position.average_cost,
             "sources": list(position.sources),
             "cost_basis_complete": position.cost_basis_complete,
             "offsetting": position.is_offsetting}
            for position in view.positions
        ],
        "analysis": holdings.concentration(view.holdings()),
    }

    if not view.complete:
        # Said at the top of the report as well as in the notes. A caller reading
        # only the analysis must not be able to miss that it describes part of a
        # portfolio - the number that is wrong is the concentration, and nothing
        # about it looks wrong.
        report["analysis"]["partial"] = True
    return report


def _analyst_work(conn, identity: str) -> None:
    request = analysis_requests.claim_next(conn, identity)
    if request is None:
        # Idle, and idle is correct here rather than suspicious. This agent works
        # only when a client asks (§115).
        return

    print(f"[portfolio_analyst] taking {request['request_id']} "
          f"({len(request['sources'])} source(s))")
    try:
        report = analyse(request)
    except AnalysisRefused as refusal:
        analysis_requests.fail(conn, request["request_id"], str(refusal))
        return
    except Exception as exc:  # noqa: BLE001
        # The request failed; the client is told that rather than left waiting.
        # The exception text is the client's only explanation, so it travels.
        analysis_requests.fail(conn, request["request_id"],
                               f"the analysis could not be completed ({exc})")
        return

    analysis_requests.deliver(conn, request["request_id"], report)
    # Positions existed in `report` and in the consolidation above, both of them
    # locals of this cycle. Nothing here writes one down, and nothing keeps a
    # reference past this return.


def main() -> None:  # pragma: no cover - process entry point
    if len(sys.argv) != 2:
        print("usage: python -m agents.portfolio_analyst <identity>", file=sys.stderr)
        raise SystemExit(1)
    identity = sys.argv[1]

    def work_fn(conn) -> None:
        _analyst_work(conn, identity)

    run_agent(identity=identity, role=ROLE, work_fn=work_fn)


if __name__ == "__main__":  # pragma: no cover
    main()
