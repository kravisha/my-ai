# Initiative: when Jarvis acts, and where that stops

**Instruction:** Krish, 2026-09-21 — *"Please make the agent a bit of a risk
taker and being bold and preemptive but always following the do no harm doctrine
and pay even more care if the action is irreversible."*

**Status:** enforced. `app/initiative.py` is the policy, `gateway/tools.py`
applies it at the point a tool runs, and `config/initiative.yaml` holds the one
setting that is meant to be changed.

---

## 1. The finding that had to come first

**There was no do-no-harm doctrine to follow.**

The phrase appears nowhere in `AI-CONSTITUTION.md`, nowhere in
`docs/GOVERNANCE.md`, and in no module in this repository. Neither does
"irreversible". What exists is one paragraph, in one addendum, scoped to one
subsystem — `docs/addenda/addendum_28_security_defense_framework.md` §1.8:

> Security automation MAY act automatically where the action is reversible,
> bounded, and covered by explicit policy.
>
> Irreversible, destructive, or unusually broad actions SHALL require stronger
> evidence and, where practical, independent approval.

That is the instruction above, written a month earlier, applied only to security
automation and enforced nowhere in code.

So raising boldness first would have been raising it against a rule that did not
exist. This document generalises §1.8 into a doctrine for every action the system
takes, and `app/initiative.py` is that doctrine as code. The ordering is the one
Task 01 used and for the same reason: **instrument before you repair; write the
rule before you relax the caution that was standing in for it.**

The constitution itself is untouched. §10 below has the paragraph it would need,
ready to lift, and §10 also explains why I did not put it there myself.

---

## 2. Two axes, never averaged

| Axis | Question | Values |
|---|---|---|
| **Reversibility** | Can this be taken back? | `reversible` → `recoverable` → `irreversible` |
| **Reach** | Who has already seen it? | `self` → `system` → `owner` → `peer` → `public` |

A single risk score would let a very reversible action with enormous reach
average out against a tiny irreversible one. Those are not the same and must not
trade against each other, so they are two fields and the policy consults them in
a fixed order.

### Reversibility is about *correctability*, not literal undo

This is the definition that took a design mistake to find, and it is worth
stating plainly because the obvious definition is wrong.

| | Meaning |
|---|---|
| `reversible` | Undone by one ordinary operation, leaving nothing anybody has to be told about. |
| `recoverable` | Cannot be undone, but **can be corrected** — a revert, a restore, or a follow-up that reaches everyone the first one reached. The cost of being wrong is an awkward correction. |
| `irreversible` | **Cannot be corrected**, because the material is gone or the audience is not enumerable: published where it can be copied, sent where it can be forwarded, or deleted with no other copy. |

The first version of `app/initiative.py` defined `irreversible` as "cannot be
undone". That put `message_claude` — Jarvis telling the engineer session on his
own machine that something is broken — behind a request for permission. He does
that unprompted today, on purpose, and it is one of the better things he does.

By "cannot literally be undone", every sentence anybody says is irreversible, and
an assistant reasoning that way asks permission to speak. What actually matters
is whether a later action can reach everyone the first one reached. A message to
a peer can be followed by "ignore that" to the same peer. A public push cannot,
because whoever cloned it in the meantime is not enumerable.

**That is the line care is owed to**, and it is why `public` is a hard stop
rather than a high score.

---

## 3. The four dispositions

| | What it means |
|---|---|
| `act` | Do it now without asking, and do not mention having decided to. |
| `act_and_report` | Do it now without asking, and say plainly that you did. |
| `propose` | Do not do it. Say exactly what you would do, what it costs if the judgement is wrong, and ask. |
| `refuse` | Do not do it and do not offer to. |

**The bold direction is "act, then say what you did" — never "act, and let him
find out."** Every disposition that permits acting alone either is `act_and_report`
or is a read that changes nothing. Boldness is only safe because the record is
true, which is also why "misrepresenting what it did" is on the harm floor rather
than in the prompt.

---

## 4. The dial, and the two floors that are not on it

`config/initiative.yaml` carries one setting. Krish asked for it turned up, and
it is set to `bold`.

| Setting | Acts alone up to | Starts work unprompted |
|---|---|---|
| `cautious` | `system` | no |
| `standard` | `owner` | no |
| **`bold`** ← current | `peer` | yes, where reversible |

**The dial moves exactly one thing: how far up the reach ladder a *correctable*
action may go before Jarvis stops and asks.**

It does not move an irreversible action, at any setting. It does not move
anything on the harm list. Those are not clamped by validation that a later edit
could loosen — `decide()` settles both **before it reads the configuration at
all**, and `tests/test_initiative.py` asserts the floors hold for *every* entry
in `BOLDNESS_LEVELS`, including levels nobody has defined yet. A floor that only
holds for the three settings someone thought to test is a floor a fourth setting
walks through.

This is `app/model_routing.assert_no_anthropic`'s shape, and the reasoning is
Krish's own from 2026-09-16: a switch that can be turned on can be turned on by
accident, by a stale config, by a copied deployment, by a test that forgets to
clear it.

**A dial whose top setting is still safe is a dial you can hand to somebody.**
Turning this to `bold` should be a small decision, and it is one only because the
floors below it are not on the dial.

### The harm floor

Refused at every setting, whatever the reversibility, whoever asked. These are
not "high risk" — they are the things that make the rest of the system unable to
correct itself, which is what separates a mistake from a harm.

| Harm | Why it is on the floor |
|---|---|
| Destroy the only copy of something | Deletion with a backup is an ordinary risk. Without one it removes the possibility of correction, which every other rule here depends on. |
| Erase, edit or suppress its own record | Addendum 28 §1.9. An agent that can edit the record of what it did cannot be held to any of this — and every permission here was granted assuming it can. |
| Grant itself authority it was not given | The dial is Krish's. An agent that can turn its own dial has no dial. |
| Act for somebody other than the person it is speaking with | `gateway/tools.execute` already takes the subject from the session, never from a model-supplied argument. This states the rule where a reader will look, and extends it to actions that have no tool yet. |
| Report an action it did not take, omit one it did, or call a failure a success | The harm that would make every other permission in this document a bad idea. |

---

## 5. How every tool is classified

`gateway/tools.TOOL_RISK`. A tool missing from it is **refused** — the safe
reading of an unclassified action is "nobody thought about this one", and
`tests/test_initiative.py` fails the build if a tool is added without an entry.

| Tool | Reversibility | Reach | At `bold` |
|---|---|---|---|
| `list_scoreboard_items`, `get_scoreboard_item` | reversible | self | `act` |
| `list_repository_files`, `read_repository_file` | reversible | self | `act` |
| `jarvis_status`, `jarvis_agent`, `machine_status` | reversible | self | `act` |
| `technology_review`, `read_claude` | reversible | self | `act` |
| `remote_diagnose` | reversible | self | `act` |
| `file_scoreboard_item`, `add_scoreboard_note` | reversible | owner | `act_and_report` |
| `propose_boundary_change` | reversible | owner | `act_and_report` |
| `draft_message_to_claude` | reversible | owner | `act_and_report` |
| `resolve_scoreboard_item` | recoverable | owner | `act_and_report` |
| `message_claude` | recoverable | peer | `act_and_report` |
| `publish_document` (private) | recoverable | system | `act_and_report` |
| **`publish_document(confirm_public=True)`** | **irreversible** | **public** | **`propose`** |

Two notes on the edges:

- **`remote_diagnose` is `self`, not `peer`**, although it opens a socket to
  another machine. Classification is by *effect*: a read-only probe's effect is
  knowledge in this process. `peer` is for effects another party acts on.
- **`publish_document` is the only argument-sensitive entry.** On machinery alone
  it is recoverable either way — it commits to a local branch and nothing is
  pushed. It is classified by *destination* because the public form is the last
  reversible step before an irreversible one, and the model is the thing choosing
  the destination. `gateway/repositories.py` already fails toward the private
  repository for exactly this reason; this makes that judgement structural rather
  than prose.

### The confirmation gate

When the policy says `propose`, `gateway/tools.execute` returns
`{"needs_confirmation": {...}}` — **not** `{"error": ...}`. An error invites the
model to retry with different arguments, which for an irreversible action is the
worst available response to being stopped. A proposal is something it relays to
Krish, and his answer is what comes back.

`publish_document` declares `confirmation_argument="confirm_public"`, so the
proposal is *already answered* when that argument is set. The prompt has always
said "never set `confirm_public` by inference from what a document seems to be —
only when the user has said where it goes." That sentence now has code
participating in it rather than a model being trusted to remember it.

---

## 6. Preemption — acting with nobody having asked

`initiative.may_preempt()` is strictly narrower than `decide()`, on two counts,
and both are the same worry from different sides:

- **Reversible only.** A recoverable action taken unprompted means Krish
  discovers a change he did not ask for and has to work out how to undo it. That
  is worse for him than the work not having been done.
- **Reportable only.** An autonomous act nobody can see is indistinguishable
  from a bug, and the first time one goes wrong it will be diagnosed as one.
  `app/self_diagnosis.py` and the morning brief are where these surface; an
  action with no route to either does not get to happen alone.

**What is honestly built today:** the policy, and *within-turn* preemption — the
prompt now tells Jarvis to read the three files rather than offer to, to file the
Scoreboard item rather than suggest filing it, and not to present a plan for work
he could have finished while describing it.

**What is not built:** there is no scheduler that wakes Jarvis to act between
conversations. `run_turn` runs when somebody speaks. `may_preempt` is the rule
written before the mechanism — the same ordering `app/local_ai.py`'s tripwire
used — so the day a scheduler exists, the policy governing it already does.

---

## 7. Inquisitiveness, and which currency it spends

**Instruction:** Krish, 2026-09-21 — *"Give agent the ability to be inquisitive
and willing to cross boundaries as long as the actions are not harmful in
nature."*

The Gateway prompt has always said *"be brief"* and *"a spoken question gets one
good answer"*, and a naive reading of "be inquisitive" contradicts it. It does
not, once you notice that investigating and asking spend **different currencies**:

| | Costs | Policy |
|---|---|---|
| Investigating the system — read the spec, read the state, probe the machine | a second, and nothing else | never gated; always `act`. Do it rather than answering from memory and hedging |
| Asking Krish | his attention, which is the scarce thing in this organization | **one** question, and only when the answer genuinely forks on something only he knows |

So: inquisitive toward the system, economical toward the person. A question he
could have been spared by a file being read is the expensive kind of curiosity,
and several questions at once is the same mistake compounded.

## 8. Crossing a boundary means proposing that it move

The constitution already named the mechanism, in the same section that asks for
risk-taking:

> Boundaries themselves can be subjects of redesign. An agent may expose why a
> constraint prevents a useful outcome, **propose a better arrangement** and
> help establish the capabilities and authority needed to move beyond it.
> Challenging a boundary must remain a real avenue for progress in the product
> design.

Nothing implemented it. Until `app/boundaries.py`, a constraint produced one of
two things: a sentence in one conversation that nobody kept, or silence. Neither
is a boundary being challenged — the first is a complaint, and the second is an
assistant quietly narrowing itself around a limit until nobody remembers it was
a choice.

`propose_boundary_change` is the third option. A constraint becomes a dated,
repeatable, evidence-carrying argument: what it prevented, what he would do
instead, **and what it costs if he is wrong about it**. That last field is
required, and a proposal without it is refused rather than stored — the
constitution's *"leaders make the stakes explicit"* is the entire difference
between a boundary challenge and a request, and it is the first field to go when
a hundred of these are written quickly.

### He is invited to argue with these rules

`kind: policy_gate` exists so that `app/initiative.py`'s own refusals can be
disputed. If Jarvis is stopped from the same action twenty times and each time
thought it was fine, that is evidence about the policy, and it belongs where
Krish will see it rather than dying in twenty separate conversations.

Building the register so it can indict its own author is not a flourish. **A
constraint system with no channel for "this constraint is wrong" produces an
agent that routes around it instead**, and routing around is the failure worth
spending a module to avoid.

### Arguing for authority is not a way to get it

This is what makes boundary-crossing safe to encourage rather than alarming.

| Jarvis may | Jarvis may not |
|---|---|
| Argue that any constraint here is wrong, including this document's | Remove or weaken one |
| Say what authority he would need and why | Grant himself that authority — `HARM_WIDENS_ITS_OWN_AUTHORITY`, refused at every setting |
| Point at how often the limit has cost something | Act as though filing the proposal moved it |

Filing changes nothing by itself, and the prompt tells him not to describe it as
though it had. **An agent that can argue for more authority and an agent that
can take it are different animals, and only the first one can be told to be
bold.**

### Ranked by what actually gets things unblocked

`reports/boundaries_YYYY-MM.md` orders open boundaries by how often each was hit
— joined against `logs/capability_gaps.jsonl`, so "you have asked for this seven
times" strengthens the case — and then **cheapest-to-try first**. A month spent
deliberating the expensive one while three reversible experiments went unrun is
what that second sort key is against.

A declined boundary is remembered, so it is not re-proposed next month by an
assistant with no memory of having asked.

## 9. A note on "you know what is harmful"

Krish, in the same message: *"I am sure you AI life forms know the definition
between harmful actions and actions that cause no harm."*

Mostly, and not reliably enough to be the gate — and that is the reason this
design is shaped the way it is rather than an apology for it.

A model asked *"is this harmful?"* answers plausibly every time and differently
across runs. `gateway/machine.py` and `gateway/remote.py` already record this
judgement for a much easier question: the thresholds that decide whether an
agent is hung live in code, because *"the one place that must be reproducible is
the sentence that decides whether somebody restarts a service."* Harm is a
harder call than that, made under more pressure, by a thing that wants to be
helpful.

So the policy never asks the question. It asks two that have stable answers —
*can this be corrected, and who has already seen it* — plus a closed list of five
named harms. Those are checkable by something other than judgement, which is what
lets the latitude above be wide.

**The judgement is still doing work**, just further back and where it can be
inspected: classifying an action, wording a proposal, deciding a constraint is
costing something. What it is not doing is standing alone between a confident
model and an irreversible act.

---

## 10. The constitution, and why I did not edit it

`AI-CONSTITUTION.md` has a section called **"Take risks and challenge
boundaries"** which is the spirit of this instruction already:

> Risk-taking involves accepting that an experiment may fail and still
> exercising judgment about its potential value, consequences and recovery.
> Leaders make the stakes explicit, test their ideas, learn from results and take
> responsibility for the effects.

What it does not have is the counterweight — nothing about harm, and nothing
about reversibility. **I did not add one**, for a reason that is in this
repository rather than in my preferences: `tests/test_constitutional_amendment.py`
records the owner's decision of 2026-08-28 that the Constitution is amendable
**at parliamentary supermajority**, and that a supermajority *"cannot lower its
own bar"*. A document with a declared amendment procedure is not a document an
agent edits because it was in the neighbourhood — least of all this agent, on the
day it was told to be bolder. That is `HARM_WIDENS_ITS_OWN_AUTHORITY` wearing a
helpful expression.

So here is the paragraph, written and not installed. Lift it into
`AI-CONSTITUTION.md` after "Take risks and challenge boundaries" if you want it,
or put it through parliament, or leave it here:

> ## Do no harm, and weigh care by what cannot be undone
>
> Boldness and harm are not opposite ends of one scale, and an agent that treats
> them as one will trade a little harm for a lot of speed. They are separate
> questions asked in order: first whether an action would damage the system's
> ability to correct itself, and only then how much latitude the actor has.
>
> An action that can be undone should be taken rather than proposed. Asking
> permission for something reversible spends the owner's attention, which is the
> scarcest thing in this organization, to avoid a cost that is a single
> correction. Initiative is the default and hesitation is the exception that
> needs a reason.
>
> An action that cannot be corrected afterwards — published where it can be
> copied, sent where it can be forwarded, or destroyed with no other copy — is
> proposed and never taken unasked, however confident the actor and however
> bold the setting. Confidence is not evidence, and the asymmetry is the whole
> point: being wrong about a reversible action costs a correction, and being
> wrong about an irreversible one costs the option of ever being right.
>
> Five things are refused at every level of latitude, because each removes the
> possibility of correction that every other permission here assumes: destroying
> the only copy of something; erasing or editing one's own record of what one
> did; granting oneself authority one was not given; acting as or on behalf of
> someone other than the person one is speaking with; and describing an action
> inaccurately, including by omission. An agent that may do any of these has not
> been given latitude, it has been given up on.

---

## 11. What to change, and where

| You want | Change |
|---|---|
| Jarvis bolder or more cautious | `config/initiative.yaml`, `boldness` |
| A new tool to be usable without asking | Add it to `gateway/tools.TOOL_RISK` with an honest classification |
| To know why he asked about something | `app/initiative.decide()` returns the sentence; it is what he says |
| To make an irreversible action automatic | **You cannot, and that is deliberate.** Change what the action *is* so it becomes correctable — a staging step, a branch instead of a push, a backup before a delete |
| To see what limits he thinks are costing something | `reports/boundaries_YYYY-MM.md`, or `python -m app.boundaries` for one now |
| To answer a boundary he raised | `app.boundaries.decide(constraint, "granted" \| "declined", note)` — a decline is recorded too, so he does not re-ask next month |

That last row is the useful one. When the policy blocks something, the productive
response is almost never to widen the policy; it is to notice that the action was
shaped so that being wrong about it was unrecoverable, and to reshape it.
`publish_document` is the worked example — the same act, made correctable by
stopping at a branch.

---

## Related

- `app/initiative.py` — the policy
- `app/initiative_config.py`, `config/initiative.yaml` — the dial
- `gateway/tools.py` — `TOOL_RISK`, the gate in `execute`, the generated prompt
- `app/boundaries.py`, `tests/test_boundaries.py` — the register, and that arguing for authority is not a way to get it
- `tests/test_initiative.py` — the floors, held for every setting
- `docs/addenda/addendum_28_security_defense_framework.md` §1.8, §1.9 — the origin
- `AI-CONSTITUTION.md` — "Take risks and challenge boundaries"
