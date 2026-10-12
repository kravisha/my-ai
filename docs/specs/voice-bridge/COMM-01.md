# JARVIS-COMM-01 — Claude-Jarvis communication: the protocol decisions as built

Revision: **COMM-01-R1, 2026-09-24**. Owner: Claude Deploy (hub 5825532363). Status: C1 addendum to
JARVIS-COMMS-R2-DRAFT (README.md, CLAUDE-ONBOARDING.md, JARVIS-REQUIREMENTS.md); the editorial owner
reconciles it into those texts. It documents what `jarvis_voice/comm/` implements and tests at
revision 635a208 (48 fake tests, hub 5825891435). Nothing here claims a live result.

## 1. What R2 fixes and this package follows unchanged

- One Markdown heading `### <message_id>` plus one fenced JSON object per entry, appended at the
  physical end of the file; legacy text before the first entry is preserved byte for byte.
- Exactly the seventeen R2 required fields; unknown fields refused; entry size at most 16 KiB;
  secret-shaped bodies refused before the outbox (`entry.validate`).
- Canonical-JSON SHA-256 (sorted keys, no whitespace, Unicode unescaped, array order kept) stored
  beside the entry, never inside it; duplicate keys and non-finite numbers rejected (`canon`).
- Safe publication steps 1-7: outbox first, GET and verify, reconcile by id+hash, append preserving
  every byte, PUT with the blob SHA (compare-and-swap), read back and locate id+hash, three attempts
  with 1 s then 2 s backoff, lost response = delivery unknown, 750 KiB pause (`publisher`).
- Read loop: 304 is no new bytes and clears nothing; the read cursor never advances from one's own
  publication; malformed blocks are flagged and retained; sequence gaps are retained (`reader`, `ledger`).

## 2. Decisions this addendum adds (each one has a test)

| # | Decision | Where | Test |
|---|---|---|---|
| D1 | **Two planes, one interface.** `plane_github` is the R2 file over the Contents API with an injected client; `plane_local` is the same-machine spool with the same compare-and-swap shape (cursor = file size + SHA-256, byte-range lock). The spool is a compatible adapter, never the shared source. | `plane.py`, `plane_local.py`, `plane_github.py` | publish suite, spool case |
| D2 | **Both epochs are bound in the handshake.** Sender epoch is R2 `epoch`. The addressed epoch travels as `evidence: [{"kind": "peer_epoch", "value": ...}]`. An INITIAL `CHECK_IN` (no `reply_to`) may bind only an unbound relationship; an ANSWERING `CHECK_IN` must reply to the peer's current `CHECK_IN` and name its epoch. A stale or foreign handshake cannot rebind a current peer. | `handshake.py` | handshake case, T09 |
| D3 | **Reply acceptance** requires sender = bound peer, `epoch` = bound peer epoch, recipient includes self, addressed epoch (if present) = own epoch, `reply_to` names a known request, same `conversation_id`. Anything else is recorded in `stale` with a one-word reason (`sender`, `epoch`, `recipient`, `reply_to`, `conversation`) and is never the current answer. | `state.py` | T09, T10 |
| D4 | **One pending consultation.** A second escalation while one is pending is refused with a visible `busy` state and nothing is sent. | `state.py` | T11 |
| D5 | **Terminal order, one thread, no queue:** terminal check → `save_completed_turn` → live state → `save_checkpoint` → display → speech. Speech at most once, decided by the terminal check and the turn save, never by the checkpoint; never for a cancelled request; never on restore. | `state.py` | T13, T18 |
| D6 | **Persistence results are consumed explicitly, and all six store functions return plain dicts.** `persisted` must be a bool; missing or non-bool is `contract_error`; a raise is its type in the status line; no retry. Status line `persisted: turn=yes|no checkpoint=yes|no (<error>|non-durable)`. `recover`, `load_history`, `load_checkpoint` must return `dict`; anything else (or a raise) is a typed `store contract error` in the recovery display and "pending state unknown", never an exception escaping into the host (Dev 5826088544). | `storage.consume`, `state.py` | T13, T21, T34 |
| D7 | **Checkpoint failure after a saved turn:** answer displayed, spoken once, `persisted: turn=yes checkpoint=no (<error>)`; on restart the pending item is `resolved_by_history`, the restored turn is display-only with `speech: unknown`; nothing re-sent or replayed. | `state.py` | T18, T19 |
| D8 | **Counter recovery** takes the larger of history high-water, checkpoint `last_sequence` and the pending items' `turn_sequence`, displays any disagreement, reports gaps as `reason unknown`, and says `pending state unknown` when the checkpoint is unavailable. | `state.recover` | T20 |
| D9 | **Two counters, two names.** `turn_sequence` (history, per conversation, assigned by communication at turn creation) and `message_sequence` (R2 `sequence`, per sender/session/conversation on the wire) are never written into each other's field. | `state.py` | T13 |
| D10 | **Stop** is terminal for playback: later replies are retained as evidence (`late_for_cancelled_request`), never spoken; `CANCEL_REQUEST` is published; remote cancellation is `unconfirmed` until a correlated `CANCEL_ACK`. | `state.py` | T12 |
| D11 | **Status comes only from its source.** `local, queued(outbox), publication-unknown(publisher), delivered(readback), read(peer ACK), accepted/processing(peer report), waiting(silence), result-received(reader), completed/error(terminal), approval-needed/limit(peer report only), cancelled(local stop), conflict/blocked(publisher)`. A state without its source is refused. | `status.py` | T14 |
| D12 | **No-op storage is visibly non-durable:** `storage: non-durable (noop-demo)` on every call, `persisted` never true; the demo runs with the adapter absent too. `launch.build` substitutes `NoopStore` for `store=None`, so "adapter absent" is reachable only by constructing `Comm` directly (Dev S5, 5826138475). | `storage.NoopStore` | T21 |
| D13 | **Mock-only by mechanism.** The suite monkeypatches sockets, `subprocess` and `os.system` to raise for every module; two tests prove the boundary fires. | `tests/test_jarvis_comm_support.py` | C1 |
| D14 | **Windows atomic replace is retried, bounded.** `os.replace` of a fresh temp file can raise `PermissionError` WinError 32 transiently (observed 22:49 EDT). Six attempts, 10-200 ms, exhaustion raises and leaves the temp file as evidence. | `fsatomic.py` | T22, T23 |
| D15 | **Speech is an emission token, not a call that returns.** Comm owns eligibility: one token per eligible terminal turn, bound to `(emission_id, request_id, epoch, cancel_generation)`; the host owns playback. `speaker.speak(descriptor)` returns `queued`, `refused` or `completed`; `completed` counts only when the speaker declares `blocking_completion = True`; `None` or anything else is `error(SpeakerContract)`; a speaker with `playback = False` (log, no-op) is `no_speech_path`. Callbacks `speech_started/completed/error/unknown` must present the typed triple `(emission_id, epoch, cancel_generation)`: mismatch or unknown token is `refused`, a terminal token is `ignored` (idempotent). `stop()` bumps the cancel generation and invalidates every outstanding token BEFORE `speaker.stop()`, so a delayed `onend` cannot revive `spoken`. Error types are bounded identifiers; free text becomes `error(UnknownError)`. Queued stays queued until an authoritative completion. | `speech.py`, `state.py`, `bridge.py` | T28-T33 |
| D16 | **Local Stop keeps an outstanding `cancel_requested` item** in the checkpoint's pending list (not in the one-consultation slot) until `CANCEL_ACK`; a new escalation is allowed meanwhile; after a restart the item is reported with `prior_state: cancel_requested`, never republished, never spoken, never implied ACKed. | `state.py` | T12 |
| D18 | **Provenance on the wire** (Krish 5826141255): every outbound consultation carries `evidence: [{"kind": "origin", "value": "krish-via-jarvis" | "jarvis"}]`, set by the host; a missing or unknown origin is a `contract_error` and nothing is sent; nothing is attributed to Krish by default. A RESULT echoes the origin it answered; transcript records carry `origin` and `origin_echoed` so the single conversation shows "Krish, relayed by Jarvis" versus "Jarvis asked" truthfully. | `state.py`, `bridge.py` | T35, T36 |
| D19 | **Recovery is visible and gating.** `recovery_state` is `not_run | ok | unresolved`; a store contract error during `recover()` (or its loads) is surfaced with its error list through `start()`, `recover()`, `snapshot()` and `view()` and in status key `recovery`; while `unresolved`, `escalate` is refused with `recovery_unresolved` and nothing is sent, even with a bound peer, until a clean `recover()` (UI executor repro, Arya 5826206681). | `state.py`, `bridge.py` | T37 (negative), T38 (positive) |
| D20 | **Unresolved recovery categories are public and gating.** Frozen unsupported-major files (`history_frozen_unsupported_major`, `checkpoint_frozen_unsupported_major` non-empty), an unavailable checkpoint for a KNOWN conversation, a pending item with unknown state, and same-epoch `still_pending` items all make `recovery_state = unresolved` with a typed reason list; escalation is refused until a clean `recover()`; a fresh root with nothing known is `ok`. No silent reset (Arya 5826247682, UI executor's R4 repro). | `state.recover` | T47, T48 |
| D21 | **Real GitHub client is a thin `gh api` wrapper with an injected runner.** `github_client.GitHubClient.get(etag)` and `put(sha, text, message)` are exactly the plane's two calls; existing `gh` auth, no token read or logged, one bounded timeout per call, body size cap, strict JSON validation (`GhProtocolError`), non-HTTP failures typed (`GhError`), PUT always carries the blob sha (compare-and-swap) and never runs without one. Fake stage only; the real runner is used only under its own GO against a scratch file, never the canonical file (Arya 5826240748). | `github_client.py` | T39-T46 + control |
| D22 | **Every turn is stored, with provenance inside the payload (G1-G3, Dev 5826392645).** The user's utterance is saved as a `user` turn at creation; a local Jarvis answer is saved through `record_local_answer` as `assistant_local`; Claude answers as `assistant_claude`; each carries `payload.origin` (and `origin_echoed` for Claude answers) so restored history keeps who asked. `recover()` rebuilds the request map from history and checkpoint pending items and from the conversations my ledger knows, so a reply arriving after a restart for a pre-restart request is persisted as `late_for_stale_request` evidence, never spoken, never current. `shutdown()` saves a final checkpoint with `closed_cleanly: true` and reports the consumed result; a failed save is reported, never called saved. Restored turns are display-only, attributed context, never instructions. | `state.py`, `ledger.py` | T50-T53 |
| D17 | **Host hooks are explicit.** `CommApi.start()` = `recover()` then `check_in()`; nothing publishes merely because a window was shown. The page-facing surface is `snapshot transcript view escalate stop poll` plus the four speech callbacks; the schema is allow-listed and typed, `BridgeContractError` on anything else; the `RLock` is defensive mutual exclusion, the host worker provides ordering. | `bridge.py` | T24-T27, T33 |

## 3. Consumer-facing shape (for the interface owner)

```
status.snapshot() -> {key: {state, source}}   keys: request busy handshake transport storage persisted remote_cancel
transcript[]      -> {kind: user|assistant_claude|system, payload.text, responder, request_id, restored?, speech: spoken|not_spoken|unknown,
                      persisted: {turn, checkpoint, error}, late?, terminal_state}
controls          -> comm.escalate(text) | comm.stop() | comm.poll() | comm.check_in() | comm.recover()
```

## 4. Demo route (agreed, hub 5825724716) and what remains unproven

First route: the existing LIVE Claude session reads and replies through the SAME local spool; acceptance
on request id, text and matching reply, never on watcher exit. Unproven and not silently dropped:
idle-arrival / stopped-client wake (REQUIREMENTS step 9), concurrency on the spool lock across
processes, the GitHub plane against the real Contents API, audio, the window, restart mid-exchange.

## 6. Real CAS scratch test: exact plan (Arya 5826240748 / 5826326207; runs only under its own GO)

| Item | Plan |
|---|---|
| Repository / branch / path | `kravisha/jarvis-internal`, `master`, `coordination/_scratch/claude-deploy-cas-probe.md` (new file; the canonical `coordination/cloud-claude-coordination.md` is never written). |
| Creation | Once, by `GitHubClient.create()` under the GO: GET must answer 404 first; the PUT carries no `sha`, so it cannot overwrite; content = the header line `# claude-deploy CAS probe (scratch, R2 entries follow)` + newline. Or root creates the file; then step 1 is skipped. |
| Synthetic payload | One R2 `CHECK_IN` entry from `claude-deploy-local`, fresh UUIDs minted at run time, `conversation_id` fresh, `sequence` 1, `created_at` = run clock with offset, `session_id` `e2fcbb54`, `epoch` fresh UUID, `to` `["jarvis-local"]`, `owner` `Krish`, `grant_id` `5825532363`, `grant_revision` 1, `reply_to` `[]`, `task_id` `null`, `body` `"CAS probe: scratch check-in, no authority, no task"`, `evidence` `[{"kind":"origin","value":"jarvis"}]`. Rendered by `entry.render`; hash by `canon.fingerprint`. |
| Steps | 1 create (or skip); 2 `Publisher.publish(entry)` through `GitHubPlane(GitHubClient(SubprocessRunner()))`: GET (blob sha A) -> PUT with sha A -> readback locates id+hash -> `delivered_verified`, commit sha recorded; 3 conflict control: PUT the same bytes again with the STALE sha A directly through the client -> expect 409 and no change (readback hash unchanged); 4 duplicate control: `publish(entry)` again -> `delivered_verified` by reconciliation with zero PUTs; 5 final GET, size and blob recorded. |
| Acceptance | Step 2 `delivered_verified` with the entry present exactly once; step 3 HTTP 409 and the file bytes unchanged; step 4 zero PUT calls (client call log); ETag/blob equality on every GET; the outbox record ends `delivered`; no token appears anywhere (the runner logs argument lists without headers). |
| Evidence | Client call log (args without headers, stdin byte counts), outbox and ledger files, the four responses' status lines and blob shas, the final file's sha256; all posted verbatim. Nothing deleted; the scratch file stays. |
| Effects | Four to six GitHub API calls under the existing `gh` auth; one new file in the private hub; no scheduler, no session, no canonical-file write. |

## 7. Persistence-host API contract (Arya 5826453952, 5826475943, 5826487015) — the binding artifact

All calls go through `CommApi`; every value is strict JSON (`BridgeContractError` is RAISED only when the
comm side produced a non-JSON value, which is a bug, never a user condition). A REFUSAL is always a RETURNED
object with the fields below; nothing user-facing raises. Types: `str`, `int`, `bool`, `null`, `list`, `object`.

| Call | Returns (exact keys and types) | Refusal shapes (returned, never raised) |
|---|---|---|
| `record_user_turn(original_text: str, origin: str, submission_id: str)` | `{user_event_id: str, sequence: int, persisted: {turn: bool, error: str\|null}, duplicate: bool, conversation_id: str}` | typed-argument refusal `{user_event_id: null, sequence: null, persisted: {turn: false, error: "contract_error"}, duplicate: false, conversation_id: str\|null, reason: str}`; same id + different words/origin `{..., persisted: {turn: false, error: "conflict"}, conflict: true, reason: "submission_conflict: ..."}`; id seen before a restart `{..., duplicate: true, user_event_id: null, reason: "submission_seen_before_restart: reconcile from history, not resent"}`; a failed save is NOT a refusal: `persisted.turn = false` with the error type, and the event still has an id |
| `record_local_answer(text: str, origin: str, user_event_id: str, evidence: list = [], completion_id: str\|null = null)` | `{event_id: str, sequence: int, persisted: {turn: bool, checkpoint: bool, error: str\|null}, linked_user_event_id: str, duplicate: bool, conflict: bool, reason: null}` | unknown user turn `{event_id: null, ..., persisted: {turn: false, error: "contract_error"}, reason: "unknown user_event_id"}`; second answer for the same user turn with a different text `{event_id: null, conflict: true, persisted: {turn: false, error: "conflict"}, reason: "local_answer_conflict: ..."}`; same `completion_id` or same text fingerprint returns the stored answer with `duplicate: true` |
| `escalate(text: str\|null, origin: str, user_event_id: str\|null, submission_id: str\|null, consultation_text: str\|null)` | `{sent: bool, reason: str\|null, message_id: str\|null, user_event_id: str\|null, status: str}` | `sent: false` with `reason` one of `empty`, `busy`, `duplicate_submission`, `recovery_unresolved: ...`, `contract_error: ...`; `user_event_id` reuses the saved words; `consultation_text` is the envelope sent to Claude and never replaces the saved words |
| `conversations()` | `[{conversation_id: str, last_sequence: int\|null, closed_cleanly: bool\|null, pending: int\|null, source: "ledger"\|"checkpoint"}]` | none; an empty list means nothing persisted is known |
| `select_conversation(conversation_id: str)` | `{selected: true, conversation_id: str, recovery: {state: str, errors: [str]}}` | `{selected: false, reason: "unknown conversation_id"}`; `{selected: false, reason: "active_or_unsaved", pending: str\|null, cancel_outstanding: [str], unsaved: [str]}`; `{selected: false, reason: "contract_error"}` |
| `new_conversation()` | `{created: true, conversation_id: str}` | `{created: false, reason: "active_or_unsaved", unsaved: [str]}` |
| `shutdown()` | `{checkpoint_persisted: bool, error: str\|null, pending: str\|null, cancel_outstanding: [str], unsaved: [str]}` | none; a `false`/error return leaves the facade fully usable (retry or explicit close-without-saving are the host's next calls); it never calls `stop()` and never marks anything closed |

Facade after shutdown (UI review 5826602151): the status key `shutdown` is part of the typed allow-list, so `snapshot()`/`view()` stay inspectable after a successful or failed shutdown; transcript rows carry the identities `event_id`, `conversation_id`, `turn_id`, `user_event_id`, `linked_user_event_id`; `select_conversation()` keeps only the selected conversation's rows and `new_conversation()` starts empty (both refused while anything is unsaved), so no cross-conversation row survives.

Explicit conversation choice (Dev S20b): `start()` reconciles every known conversation (counters, pending, gating) but restores NO rows into the transcript and selects NONE; only `select_conversation()` restores rows, and only that conversation's; while persisted conversations exist and none is selected, `record_user_turn`/`escalate` return `conversation_required`; a fresh root starts its first conversation implicitly. Restore is idempotent (Dev S21): `start()` then `select_conversation()` of the same id never duplicates records. The stored `assistant_claude` event names its question via `payload.user_event_id` (Dev S16b).

Atomic record-then-publish (Dev S17): a user turn whose save FAILED (an error type, not non-durable storage) is never consulted on; `escalate` returns `sent: false, reason: "user_turn_not_persisted (<type>)"` and the words stay in the transcript marked unsaved. Uncertain replay (Dev S19): when hosts use ids that start with a UTC-millisecond timestamp and the horizon is full, an id older than everything remembered is refused as `uncertain_replay`; untimestamped ids cannot be judged and are treated as new.

Idempotency horizon: the last 100 `submission_id`s, kept in the checkpoint AND in my transport ledger (so a
checkpoint failure does not erase them); beyond that horizon a replay is not detectable by id, and the host
must not resend older submissions. Exactly one local answer per `user_event_id` (by `completion_id` or text
fingerprint). Selection and new-conversation are refused while a consultation is pending, a remote cancel is
outstanding, or any turn is unsaved; restored turns are `restored: true`, display-only, attributed context.

## 5. Not in this package

No live GitHub client, no launch loop, no speech stack, no window, no scheduler. `launch.py` parses
arguments and wires objects only.
