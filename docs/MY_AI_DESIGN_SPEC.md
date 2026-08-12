# MY AI — Master Design Specification

**Revised Baseline including Enhancement Addendum 1**
Version 2 — 2026-08-11

> **Provenance note**: The original MY AI Design Specification was pasted into an earlier chat session and used to scope and build Milestone 1, but was never saved to disk as its own file. Sections 1–9 below are **reconstructed** from that session's record (the approved implementation plan and conversation history), not a verbatim copy of the original document. If the original wording resurfaces, reconcile it against this reconstruction. Sections 10+ incorporate [Enhancement Addendum 1](addenda/addendum_1_universal_agent.md), kept verbatim in that file as the authoritative source for anything merged in below.

---

## 1. Vision

MY AI is a personal, local, permissioned **action and privacy layer** that sits between the user and one or more external AI reasoning models. It is not itself the reasoning model — it is the trusted layer that decides what the model is allowed to see and do on the user's behalf.

**Addendum 1 extends this vision**: MY AI's long-term destination is to become the user's **Universal Agent** — the single interface the user talks to, which in turn operates every application, service, device, and API on their behalf. The control-flow inversion is explicit:

- Today: `User → App → Function`
- MY AI: `User → MY AI → Function`

Applications become capabilities MY AI invokes, not surfaces the user personally operates. This does not replace the original privacy-layer thesis — it's the same trust boundary, extended from "what can the reasoning model see" to "what can the agent do across the user's entire digital life."

---

## 2. Core architectural components

```
                         USER
                          │  natural conversation (voice or text)
                          ▼
                     MY AI CLIENT                    (thin — §11)
                          │  secure continuous communication
                          ▼
        MY AI INTELLIGENCE / ORCHESTRATION LAYER
   ┌──────────────────────────────────────────────────┐
   │  Conversation Manager (state, latency split — §5,6)│
   │  Permission Manager (grant/revoke, risk tiers — §7)│
   │  Privacy Filter / Data Placement Governor (§8)     │
   │  Secure Local Vault (§9)                           │
   │  Memory / Preferences, 3-tier (§10)                │
   │  Universal Capability Layer → App/Device Adapters  │
   │                                            (§12,13) │
   │  Model Adapter Layer (§14)                         │
   │  Audit Log (§15)                                    │
   └──────────────────────────────────────────────────┘
                          │
                          ▼
        Apps + Services + Websites + Agents + Devices + APIs
```

Each component is detailed below. Components already implemented in the codebase are marked **[BUILT — Milestone 1]**; components introduced or substantially expanded by Addendum 1 are marked **[ADDENDUM 1]**.

---

## 3. Conversation as the primary interface `[ADDENDUM 1]`

MY AI supports natural, continuous voice interaction comparable to ordinary spoken conversation — not a command-and-response voice-assistant pattern. The user should be able to activate MY AI, speak naturally, ask follow-ups, correct prior instructions mid-stream, interrupt MY AI while it's speaking, add information while a task is in flight, receive spoken responses, and keep talking while MY AI performs work in the background.

This reopens full-duplex, interruptible voice — previously scoped *out* of the Cinema project as too costly/complex for that product. Here it is a first-class requirement, not an enhancement to defer.

---

## 4. Thin client / backend split `[ADDENDUM 1]`

The client (desktop, iOS, Android — §11) is an intelligent terminal, not the seat of reasoning. Its responsibilities: microphone access, audio capture/streaming/playback, basic UI, local notifications, secure authentication, secure local storage, device-level permissions, communication with the MY AI backend, and execution of approved local-device operations.

All sophisticated reasoning, planning, orchestration, delegation, and task management live in the backend orchestration layer. The client is the user's doorway; the backend is the intelligence.

---

## 5. Interaction latency vs. execution latency `[ADDENDUM 1]`

Two distinct latency budgets, optimized differently:

- **Interaction latency** (hearing/accepting what the user says) must be minimized — audio capture stays responsive and non-blocking; speech is streamed continuously, never record-then-submit.
- **Execution latency** (reasoning, planning, calling out to external systems, verifying results) is acceptable to take seconds or longer, provided MY AI narrates state (`THINKING`, `WORKING`, `WAITING FOR SERVICE`, `VERIFYING`, `COMPLETED`) rather than going silent.

---

## 6. Real-time audio architecture & barge-in `[ADDENDUM 1]`

```
Microphone → Streaming Speech Recognition → Conversation Manager
  → AI Intelligence → Streaming Speech Generation → Speaker/Headset
```

Speech recognition and generation sit behind replaceable interfaces — the same discipline already applied to Reel/Cinema's `VoiceProvider`/`TranscriptionProvider` abstractions — so MY AI is never permanently locked to one speech engine (e.g. Whisper).

**Barge-in is required**: if the user starts speaking while MY AI is talking, the system must detect the interruption (voice activity detection), stop or modify the in-progress response, preserve conversational context, and cancel/modify any pending action affected by the correction. This requires simultaneous listen+playback, not turn-strict request/response.

Conversation state persists across turns so the user isn't forced to restate context already established earlier in the same objective (e.g., a multi-slot booking flow).

---

## 7. Permission Manager `[BUILT — Milestone 1, extended by ADDENDUM 1]`

**As built**: `app/permissions.py` — explicit grant/revoke per named resource, persisted to `permissions.json`, checked inside the tool implementation *before* the resource is touched (never as a pre-filter the model could reason around). Milestone 1 proved this loop end-to-end for one resource (`portfolio`).

**Addendum 1 extends this** in two ways that don't change the core mechanism:
- **Learned privacy preferences** (§8 of the addendum): grants generalize beyond a single yes/no into remembered dispositions — *always allow*, *allow for this service*, *allow for this category*, *ask every time*, *local only*, *never share*, *temporary*. These must remain reviewable and revocable by the user at any time — the system never silently escalates a narrow grant into a broader one.
- **Risk-tiered actions**: not all agent actions carry the same stakes. The original design's `READ` / `PREPARE` / `EXECUTE` tiering remains the right model — reads can be low-friction, side-effecting actions require a `PREPARE` (show what will happen) step before `EXECUTE`. This becomes more important as the Universal Capability Layer (§13) adds actions with real-world consequences (sending a message, booking something) beyond Milestone 1's read-only portfolio lookup.

---

## 8. Data governance: placement + agent-assisted privacy `[ADDENDUM 1]`

MY AI does not assume all data belongs in the cloud, nor that everything must stay strictly local. Every piece of information gets a deliberate placement classification:

| Class | Meaning |
|---|---|
| `LOCAL ONLY` | Never leaves the user's device |
| `PRIVATE SYNCHRONIZED` | Encrypted, synced only between the user's own authorized MY AI instances |
| `SERVICE-SHAREABLE` | May be sent to a specific external service when required for an approved task |
| `GENERAL` | No special protection required |

This generalizes Milestone 1's `privacy_filter.py`, which already enforces an explicit allow-list before any data reaches the reasoning model — that mechanism is the `SERVICE-SHAREABLE` gate for exactly one resource today, and should extend to a per-field classification as more resources come online, not be replaced.

**Central principle: the AI manages data placement; the user manages trust.** MY AI proactively recommends boundaries ("I recommend keeping this only on this device," "I need to send your address to complete this delivery — okay?") and reuses previously-approved dispositions instead of re-asking, but final authority always rests with the user, and every disposition must be inspectable and reversible.

---

## 9. Secure Local Vault `[BUILT — deferred scope, ADDENDUM 1 specifies mechanism]`

Deferred in Milestone 1 (no credentials were in scope — a read-only mock spreadsheet isn't a secret). Addendum 1 specifies the mechanism for when it's needed: account info, credentials, tokens, preferences, device info, permission/privacy records, and app-interaction data, stored via OS-level secure-storage facilities (secure key stores, credential vaults, hardware-backed encryption) rather than as ordinary application data. Becomes in-scope at the first milestone that touches real credentials (e.g., bill payment, account login).

---

## 10. Memory / Preferences (3-tier) `[deferred, unchanged by ADDENDUM 1]`

Not needed for Milestone 1's scope; still deferred. Addendum 1's "learned privacy preferences" (§7 above) is a narrower, privacy-specific instance of this broader memory system and can be built ahead of the full 3-tier design without conflicting with it.

---

## 11. Platform-specific clients `[ADDENDUM 1]`

Universal behavior does not require a universal codebase. Desktop, iOS, and Android get separate, platform-native implementations (different security models, background-execution rules, integration mechanisms), sharing architecture, backend, protocol, capability definitions, privacy principles, and UX — not source code. **Desktop first**, per the addendum's own sequencing guidance, to validate the architecture before committing to mobile platform constraints.

Where the OS permits, the client should support persistent/semi-persistent background operation so the user isn't forced back into app-navigation between conversational turns; where prohibited, the implementation provides the closest compliant equivalent.

---

## 12. Universal Application / Capability Interface `[ADDENDUM 1, evolves the original Tool/Workflow Engine]`

The original design's Tool/Workflow Engine (single-tool dispatch, proven in Milestone 1's `app/tools/__init__.py`) generalizes into a capability abstraction layer:

```
MY AI reasoning
  ↓
Universal Capability / Communication Layer     (e.g. SEND_MESSAGE, RETRIEVE_PORTFOLIO)
  ↓
Application or Device Adapters                 (per-app/service implementation)
  ↓
Specific Apps, Services and Devices
```

The agent reasons in terms of capabilities, not specific app interfaces — `SEND_MESSAGE` rather than "the SMS app" or "the email API." Adapters may be implemented via official APIs, OS APIs, app intents, deep links, accessibility interfaces (where permitted), browser automation, local IPC, network/device protocols, or purpose-built integrations.

Milestone 1's `retrieve_portfolio` tool is the first (and currently only) capability/adapter pair under this model — the abstraction was already right, just not yet named or generalized to more than one capability.

---

## 13. Model Adapter Layer `[BUILT — Milestone 1, unaffected by ADDENDUM 1]`

`app/model_gateway.py` — intentionally thin: a single `call_reasoning_model()` wrapper around one Anthropic model call, not a full pluggable provider registry (matches the project-wide discipline of not building an abstraction until a second real implementation exists). Addendum 1 doesn't change this component directly; it just adds more callers (the Universal Capability Layer routes more capability types through the same gateway).

---

## 14. Audit logging `[BUILT — Milestone 1, extended by ADDENDUM 1's verification step]`

`app/audit.py` — append-only `audit_log.jsonl`, one entry per resource-access attempt (timestamp, action, resource, authorized, result), written whether the attempt was authorized or denied. Addendum 1 adds an explicit **outcome-verification** expectation on top of this ("MY AI verifies the result" — §17, §4's `VERIFYING` state) — actions should confirm they actually achieved what was asked, not just that the call didn't error, before reporting success back to the user. Not yet implemented; relevant once the Universal Capability Layer includes side-effecting actions.

---

## 15. Development & versioning process `[ADDENDUM 1]`

```
Baseline Specification → Working Product → Enhancement Addendum
  → Product Modification → Specification Consolidation → New Baseline → …
```

Each enhancement is implemented against the existing codebase (preserving working functionality unless the enhancement requires changing it) *and* merged into this master spec in place — never left as a standalone bolt-on document. This file is that baseline going forward; the next addendum, if any, merges into this file the same way Addendum 1 merged into the reconstructed original.

---

## 16. Implementation status

**Built (Milestone 1)**: Permission Manager (layer 1 — resource-level grant/revoke), audit log, privacy filter, one capability (`retrieve_portfolio`) via the tool-use loop, thin Model Adapter Layer, CLI client. Verified end-to-end: grant → real answer → real analysis → revoke → correct refusal, all four interactions audited.

**Built (Milestone 2 — data governance, §7–§8)**: per-field data-placement classification (`app/data_classification.py` — `LOCAL_ONLY`/`SERVICE_SHAREABLE`/...), enforced unconditionally by `privacy_filter.py` with no user prompt required; a second, independent permission layer (`app/privacy_preferences.py`, layer 2 — forwarding disposition) that gates whether already-read `SERVICE_SHAREABLE` data may be sent to the external reasoning model, learned on first use (`always`/`once`/`never`) and reviewable/resettable via `show preferences` / `reset preference <key>`. The consent negotiation happens in the orchestration layer (`main.py`), pausing the tool-use loop *before* the model is told anything — the model never participates in deciding what may be shared, only in explaining the outcome afterward. Verified end-to-end: first-use consent prompt, no re-prompt on subsequent questions once a disposition is set, `LOCAL_ONLY` field (`account_id`) never reaches the model or either log file, `never` disposition and revoked-permission denials are distinguishable in both the audit log and the model's phrasing to the user.

**Not yet built**: streaming/conversational voice with barge-in, thin-client/backend network split (still a single local process), Secure Vault, 3-tier memory, Universal Capability Layer beyond one capability, platform-specific clients, outcome verification, `PRIVATE_SYNCHRONIZED` data class (defined but has no sync target to implement against yet).

Future milestones (voice, capability layer generalization, thin client split) remain to be scoped as separate implementation plans when prioritized.
