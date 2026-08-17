# Public / Private Boundary

The rule this repository is maintained under, so the boundary stays a practice rather than a one-off
migration.

## The rule

Public code and documentation explain **what the system does** and the **technical how** an engineer
needs to maintain, test, integrate and safely operate it.

The **why** — organizational philosophy, strategic rationale, the reasoning behind institutional
structures — is held privately and referenced by identifier.

## Writing a comment

Ask: *would an engineer need this to correctly and safely understand or change the implementation?*

**Yes → it stays public**, in full. That includes invariants, concurrency requirements, error
handling, non-obvious mechanics, data-integrity constraints, security requirements, and — importantly
— warnings about changes that would silently break something. A comment saying *"this constant must
exceed the measured drain time or the feature is inert"* is a technical fact, not philosophy, and
removing it would cost far more than it protects.

**No, and it primarily explains organizational philosophy or strategy → it moves**, replaced with:

```
Internal rationale: INT-PHIL-0007
```

Nothing more. The identifier is opaque by design: a reader learns that governing reasoning exists,
not what it says. Authorized agents resolve it in the private repository.

## What must never be removed to protect philosophy

- Anything required for correctness, safety, security, data integrity, or licensing
- API contracts, schemas, parameter and return semantics
- Warnings about non-obvious edge cases
- Test assertions and the behavioural requirement a test encodes

Tests may lose their *rationale* prose; they must never lose their *specificity*. Do not weaken a test
to conceal why it exists.

Never make code confusing in order to conceal reasoning. Readable code and protected philosophy are
compatible, and obscurity is not a control.

## What this boundary is not

**It is not a security control.** It protects intellectual property. It must never be relied on to
protect credentials, keys, authentication secrets, authorization boundaries, or customer data — those
require real access control and secret management, independently of documentation classification.

## Known limitation

This boundary was adopted partway through development. Comments written before it remain in this
repository's git history, and removing them retroactively would require rewriting the content of
nearly every commit — disproportionate risk for material that is already indexed. The genuinely
portable material (the constitution and organizational charter) *was* removed from history when it
was separated.

Going forward the boundary holds. Historically it does not, and stating that is more useful than
implying otherwise.

## Checklist for new work

1. Is this **what** the system does? → public
2. Is this technical **how**, needed to maintain it safely? → public
3. Is this proprietary **why**? → private, referenced by ID
4. Does the private entry exist and is it reachable by authorized agents?
5. Am I relying on secrecy for something that needs real access control?
