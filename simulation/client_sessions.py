"""Simulated clients: who asks, and who says whether it was any good (TASK_QUEUE
TQ-77; docs/SPEC_RECONCILIATION.md §114, §115).

Owner direction, 2026-08-27, on the session:

> *"Client requests service and requested service is provided by the agent. After
> services are provided the client expresses satisfaction or disappointment and
> ends the session and after that all client data is discarded by the system."*

## The satisfaction is the grading signal, and this is what makes it possible

§115 supplied something better than any dimension derivable from a report: **the
client says whether it was any good.** §114 had been casting about for what to
grade a portfolio analysis on, given that `grades`' existing dimensions
(relevance, novelty, evidence quality) are shaped for a market *finding*.

The obstacle is that a real client cannot tell you whether a report about their
portfolio is correct — that is why they asked. **A simulated client can**, because
the exercise knows what it gave them: `simulation/exchange.truth_for` is the
account's real contents, and the report either accounts for them or does not.

So a simulated client's verdict is informed rather than random, and that is the
whole reason this module can produce a grading signal at all. TQ-76 builds the
curriculum on top of it.

## What a simulated client actually checks

Not "is the arithmetic right" — that is `tests/test_consolidation.py`'s job and a
client cannot see it. What a client *can* notice, and what this checks, is what a
client would actually be let down by:

- **Did I get every account I named?** A report that silently omits one is the
  failure that looks like success.
- **If something was missing, was I told?** A partial answer is fine. A partial
  answer presented as complete is not, and the difference is the whole of §110
  §4.5 and TQ-78's `complete` flag.
- **Does the total match what I hold?** The one a real client checks first,
  against their own statements — and the one a quietly-partial broker response
  (`BEHAVIOUR_PARTIAL`) defeats unless the analyst noticed.
- **Was anything invented?** A price where this system has none, a position I do
  not hold.

Each maps to a specific failure this system has rules against, so a
disappointment is traceable to a rule rather than to a mood.

## The session ends, and ending it is the test

`disconnect()` calls `analysis_requests.discard_session`, and an exercise that
did not disconnect would leave the client's report on disk — which is exactly the
condition §111 forbids and exactly what an exercise is supposed to prove does not
happen. So the disconnect is part of the simulated client rather than something
the harness remembers to do afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend import analysis_requests, portfolios

VERDICT_SATISFIED = "satisfied"
VERDICT_DISAPPOINTED = "disappointed"
VERDICTS = (VERDICT_SATISFIED, VERDICT_DISAPPOINTED)


@dataclass(frozen=True)
class Complaint:
    """One specific thing the client is unhappy about.

    A reason rather than a score, because *"disappointed, 0.4"* tells a
    curriculum nothing it can train against. Every complaint here names the rule
    it is about, so TQ-76 can grade behaviour rather than sentiment."""

    code: str
    detail: str
    rule: str


@dataclass
class SimulatedClient:
    """An imaginary client with a session, sources, and an opinion.

    Holds what it asked for and what it really owns, so that its verdict is
    ground truth rather than guesswork - see the module docstring on why a real
    client could not do this."""

    client_id: str
    session_id: str
    sources: list
    truth: dict = field(default_factory=dict)
    request_id: str | None = None

    def owner(self) -> portfolios.OwnerContext:
        return portfolios.for_client(self.client_id)

    def request_analysis(self, conn, requested: str = "concentration") -> str:
        """Ask for the analysis. **The same call the Gateway route will make.**

        The HTTP hop is missing and that is stated rather than glossed: TQ-73
        builds the route, and until it does, this reaches
        `analysis_requests.submit` directly. Everything below that point - the
        queue, the claim, the analyst, the delivery, the collection - is the real
        path, so what an exercise does not yet exercise is one function call and
        a socket."""
        self.request_id = analysis_requests.submit(
            conn, session_id=self.session_id, owner=self.owner(),
            sources=self.sources, requested=requested)
        return self.request_id

    def collect(self, conn):
        return analysis_requests.collect(
            conn, session_id=self.session_id, request_id=self.request_id)

    def judge(self, answer) -> dict:
        """Satisfied or disappointed, and why (§115).

        Checks what a client can actually notice. Each complaint names the rule
        it is about, so a disappointment is traceable rather than a mood."""
        complaints: list[Complaint] = []

        if answer is None:
            complaints.append(Complaint(
                "no_answer", "I asked for an analysis and never got one.",
                "§115: the client is told, one way or the other"))
            return self._verdict(complaints)

        if answer.get("status") == analysis_requests.STATUS_FAILED:
            complaints.append(Complaint(
                "refused", f"I was told this could not be done: {answer.get('detail')}",
                "a refusal is an answer, but it is not the one I asked for"))
            return self._verdict(complaints)

        report = answer.get("result") or {}
        named = {source["name"] for source in self.sources}
        reported = set(report.get("sources") or ())
        failed = {failure["source"] for failure in report.get("failed_sources") or ()}

        missing = named - reported - failed
        if missing:
            complaints.append(Complaint(
                "account_vanished",
                f"I named {sorted(named)} and {sorted(missing)} is in neither the "
                "report nor the list of what could not be reached.",
                "§110 §4.5: an account that silently disappears is the failure that "
                "looks like success"))

        if failed and report.get("complete") is not False:
            complaints.append(Complaint(
                "partial_presented_as_complete",
                f"{sorted(failed)} could not be reached, and the report does not say "
                "this is part of my portfolio rather than all of it.",
                "TQ-78: a partial consolidation presented as complete is a portfolio "
                "missing an account, invisibly"))

        expected = self._expected_positions(exclude=failed)
        got = {position["symbol"] for position in report.get("positions") or ()}
        unaccounted = expected - got
        if unaccounted and report.get("complete") is not False:
            complaints.append(Complaint(
                "positions_missing",
                f"{sorted(unaccounted)} are in my accounts and not in this report, and "
                "nothing says anything was missing.",
                "a broker that quietly returns part of an account produces a report "
                "that is wrong and looks right"))

        invented = got - self._expected_positions()
        if invented:
            complaints.append(Complaint(
                "positions_invented",
                f"{sorted(invented)} are in this report and I do not hold them.",
                "never fabricate: absent is absent"))

        analysis = report.get("analysis") or {}
        if analysis.get("priced") is True:
            complaints.append(Complaint(
                "priced_without_prices",
                "This report values my positions, and nobody has real prices for them.",
                "§101/§113: is_priced is LIVE only; a simulated price on real positions "
                "is synthetic output presented as somebody's money"))

        return self._verdict(complaints)

    def disconnect(self, conn) -> int:
        """End the session, and everything goes (§115).

        Part of the client rather than of the harness on purpose: an exercise
        that forgot to disconnect would leave a report on disk, which is the
        condition §111 forbids and the one an exercise exists to prove does not
        arise."""
        return analysis_requests.discard_session(conn, self.session_id)

    # --- internals -------------------------------------------------------------

    def _expected_positions(self, exclude=()) -> set:
        return {holding.symbol
                for name, held in self.truth.items() if name not in exclude
                for holding in held}

    def _verdict(self, complaints) -> dict:
        return {
            "client": self.client_id,
            "verdict": VERDICT_SATISFIED if not complaints else VERDICT_DISAPPOINTED,
            "complaints": [
                {"code": c.code, "detail": c.detail, "rule": c.rule} for c in complaints],
        }


def run_session(conn, client: SimulatedClient, analyst_cycle,
                requested: str = "concentration") -> dict:
    """One complete exercise: ask, wait, collect, judge, disconnect.

    `analyst_cycle(conn)` is called to let the analyst work - in an exercise that
    is `agents.portfolio_analyst._analyst_work`, and in the harness it is the
    real agent process doing its own cycle. **Injected rather than imported**, so
    this module never reaches into `agents/` and an exercise can run against a
    live agent or a direct call without changing.

    Returns the verdict, and leaves nothing behind: the disconnect runs whether
    the judgement was good or bad, in a `finally`, because a failed exercise that
    left a client's report on disk would be the worst possible outcome of a test
    written to prove that does not happen."""
    try:
        client.request_analysis(conn, requested=requested)
        analyst_cycle(conn)
        answer = client.collect(conn)
        verdict = client.judge(answer)
        verdict["request_id"] = client.request_id
        return verdict
    finally:
        client.disconnect(conn)
