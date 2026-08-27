LIVING DOCUMENTATION STANDARD

1. PURPOSE

Jarvis shall maintain one authoritative living documentation system that continuously reflects the current design, architecture, requirements, implementation status, operating principles, and future work of the organization.

The purpose of the living documentation is to provide one clear source of truth for both humans and AI agents.

It must always explain:

- What Jarvis is.
- How Jarvis is organized.
- How the major parts fit together.
- What has already been implemented.
- What is currently being developed.
- What remains to be developed.
- What is being tested.
- What is ready for pre-alpha, alpha, beta, or production.
- What important issues, gaps, risks, and unresolved questions remain.
- Why important architectural decisions were made.

The living documentation is not intended to become a collection of disconnected specifications.

It must remain one coherent body of knowledge.

2. SINGLE AUTHORITATIVE SOURCE

There shall be one authoritative documentation structure for the Jarvis system.

New specifications, design ideas, architectural decisions, changes, clarifications, and corrections shall be incorporated into that structure.

New documents may be created temporarily during design and discussion, but important approved information must ultimately be merged into the authoritative living documentation.

The goal is to avoid having the true design scattered across many separate documents.

The authoritative documentation must always represent the best current understanding of the system.

3. LIVING DOCUMENT PRINCIPLE

The documentation shall evolve together with Jarvis.

Whenever the architecture changes, the documentation changes.

Whenever a requirement changes, the documentation changes.

Whenever a new department, agent capability, workflow, policy, data structure, or operating principle is introduced, the documentation changes.

Whenever implementation status changes, the documentation changes.

Whenever testing reveals a gap, problem, limitation, or new requirement, the documentation changes.

The documentation therefore becomes a living representation of the organization.

4. COHERENT

The documentation must read as one system.

New information must not simply be appended randomly.

When a new specification is received, it must be placed into the correct part of the architecture.

Related sections should be updated together.

Duplicate explanations should be consolidated.

Conflicting descriptions should be identified and resolved.

Old wording that is no longer correct should be replaced, while important history should remain available through versioning or change records.

A reader should not have to search through many disconnected notes to understand how the system works.

5. CONSISTENT

The same concepts must use the same names throughout the documentation.

For example, if a component is called Parliament, it should not later be called Governance Council unless the name has formally changed.

Roles, departments, environments, phases, statuses, and architectural concepts should use consistent terminology.

If a definition changes, all affected documentation should be reviewed for consistency.

Contradictions must not be allowed to accumulate silently.

6. CONTINUOUS

Documentation maintenance is part of development.

It is not something postponed until the project is finished.

Every meaningful design or implementation change should cause the relevant documentation to be reviewed and updated.

The documentation must remain useful throughout:

- development;
- simulation;
- historical-data operation;
- pre-alpha;
- alpha;
- beta;
- QA;
- UAT;
- production;
- post-production evolution.

7. SIMPLE LANGUAGE

The documentation must use simple, direct language wherever possible.

Complex technical terms should be used only when they are genuinely necessary.

When technical terms are required, their meaning should be clear from context or explicitly defined.

The documentation should avoid unnecessary abstraction, jargon, and elaborate wording.

The objective is understanding, not literary complexity.

8. BIG PICTURE FIRST

Major sections should explain the purpose and overall architecture before presenting implementation details.

A human or AI reading the documentation should first understand:

- what the component does;
- why it exists;
- where it belongs;
- what it interacts with;
- how it contributes to the larger Jarvis organization.

Only after that should the documentation describe lower-level technical details.

The documentation must make the architecture mentally visible.

9. HUMAN AND AI READABILITY

The documentation is written for two primary readers:

1. Humans.
2. AI agents.

It must therefore be structured so that both can understand the same system description.

Humans should be able to understand the system without reconstructing the architecture from source code.

AI agents should be able to retrieve the documentation and use it as authoritative organizational context.

Clear headings, stable terminology, explicit relationships, simple sentences, and structured status information should be preferred.

10. DOCUMENTATION STATUS

Requirements and components may carry implementation status.

A simple status model should be used.

Recommended statuses include:

TO BE DEVELOPED
The requirement or component is approved or expected but implementation has not started.

IN DESIGN
The design is actively being worked out.

IN DEVELOPMENT
Implementation is underway.

IMPLEMENTED
The planned implementation has been completed.

TESTING
Implementation exists and is undergoing testing.

SIMULATION
The capability is being exercised in simulation.

HISTORICAL VALIDATION
The capability is being tested using historical-data operation.

PRE-ALPHA READY
The capability is sufficiently stable for pre-alpha use.

ALPHA READY
The capability has reached alpha-level readiness.

BETA READY
The capability has reached beta-level readiness.

QA
The capability is in formal quality assurance.

UAT
The capability is undergoing user acceptance testing.

PRODUCTION READY
The capability has satisfied production-entry criteria.

LIVE
The capability is operating in production.

DEPRECATED
The capability remains documented but should no longer be used.

RETIRED
The capability has been removed from active operation.

BLOCKED
Progress cannot continue until a dependency or issue is resolved.

The status model may be refined later, but it should remain simple.

11. STATUS MUST NOT DAMAGE READABILITY

Status information should help the reader understand progress.

It should not turn the living documentation into a complicated project-management database.

The main architecture should remain easy to read.

Detailed task tracking can exist elsewhere if required.

The living documentation should show only the level of status necessary to understand the state of the system.

12. INTEGRATING NEW SPECIFICATIONS

Whenever a new specification is produced, the documentation process should:

1. Read the new specification.
2. Identify the concepts it introduces or changes.
3. Find the correct locations in the existing living documentation.
4. Merge the new information into those locations.
5. Remove unnecessary duplication.
6. Identify conflicts with existing documentation.
7. Resolve conflicts when the new specification clearly supersedes the old design.
8. Flag genuine unresolved conflicts for review.
9. Update implementation status where appropriate.
10. Update cross-references where necessary.
11. Preserve the big picture.
12. Verify that the resulting documentation remains coherent and easy to read.

The result should look as though the system was documented correctly from the beginning, rather than appearing as layers of patches.

13. ARCHITECTURE DOCUMENTATION

The living documentation should clearly describe the major organizational and technical architecture.

This includes, where applicable:

- Parliament;
- departments;
- agents;
- agent roles;
- agent persistence;
- shared knowledge;
- organizational memory;
- software engineering;
- simulation;
- historical-data operation;
- evaluators;
- trainers;
- security;
- business continuity;
- Department of Evolution;
- gateway;
- data stores;
- versioning;
- rollback;
- sandbox;
- build environment;
- built environment;
- release processes;
- QA;
- UAT;
- production operation.

Each section should explain both purpose and relationship to the rest of the organization.

14. AGENT PERSISTENCE DOCUMENTATION

Agent persistence is an important architectural requirement and must be represented clearly in the living documentation.

The system distinguishes between:

- persistent agents;
- temporary agents;
- shared organizational knowledge.

Persistent agents must retain their identity and relevant state across restarts.

Their persistence may include:

- identity;
- role history;
- experience;
- training history;
- performance history;
- important decisions;
- lessons learned;
- relationships and responsibilities;
- authorized long-term state.

Temporary agents may be spawned for specific work and removed when the work is completed.

Shared organizational knowledge must remain separate from individual agent persistence.

The shared knowledge base represents what the organization knows.

Persistent agent state represents what a particular continuing agent has learned, experienced, or retained as part of its identity and responsibilities.

Persistent agents become especially important by the pre-alpha stage.

15. ISSUES, GAPS, BUGS, AND FAILURES

The living documentation must make important unresolved problems visible.

Every significant issue discovered in the system should be captured through an appropriate issue or gap record.

This includes:

- bugs;
- missing capabilities;
- architectural gaps;
- implementation gaps;
- failed assumptions;
- unexpected agent behavior;
- simulation failures;
- historical-data failures;
- integration problems;
- performance problems;
- data problems;
- security concerns;
- governance problems;
- documentation contradictions.

Important issues should not disappear simply because the immediate failure has been corrected.

The organization should preserve enough information to learn from them.

16. CONTINUOUS IMPROVEMENT

Every meaningful problem should contribute to system improvement.

A completed issue should answer, where appropriate:

- What happened?
- Why did it happen?
- What component was affected?
- How was it detected?
- What was changed?
- How was the change validated?
- Could the same class of problem happen elsewhere?
- What should the organization learn?
- Should a policy, procedure, test, training item, or architectural rule change because of it?

Lessons learned should be incorporated into the appropriate part of the living documentation or organizational knowledge.

17. DOCUMENTATION DURING DEVELOPMENT

During early development, some areas will naturally remain incomplete.

The documentation should say so clearly.

It is acceptable for sections to contain:

- open questions;
- assumptions;
- design alternatives;
- pending decisions;
- implementation gaps;
- incomplete components.

However, these must be labeled clearly so that an unfinished idea is not mistaken for an implemented capability.

18. DOCUMENTATION DURING SIMULATION AND HISTORICAL PHASES

Simulation and historical-data operation will expose weaknesses that cannot be predicted during initial design.

The living documentation must absorb those findings.

When simulation reveals a flaw:

- document the flaw;
- identify its architectural significance;
- record the corrective action;
- update the design if necessary;
- update testing requirements;
- update training material when appropriate.

The same process applies during historical-data validation.

These phases are part of the system's learning process, not merely testing exercises.

19. DOCUMENTATION BEFORE GO-LIVE

Before production go-live, the living documentation must accurately reflect the system that actually exists.

There must not be a large gap between documentation and implementation.

Before go-live, the organization should review the documentation and confirm:

- implemented architecture matches documented architecture;
- critical components have correct status;
- unresolved gaps are visible;
- agent persistence requirements are implemented;
- shared knowledge architecture is implemented;
- versioning and rollback are documented;
- software department responsibilities are documented;
- Claude Code dependency has been eliminated as required;
- QA findings are reflected;
- UAT findings are reflected;
- production operating procedures are understandable.

20. SOURCE OF TRUTH FOR DEVELOPMENT

External development tools such as Claude Code should use the living documentation as a primary source of architectural truth during the bootstrap phase.

When new specification documents are supplied, Claude Code should incorporate the approved information into the internal authoritative documentation rather than allowing many disconnected design documents to accumulate.

As the internal Software Engineering Department matures, it should inherit this responsibility.

Eventually the internal Software Engineering Department becomes responsible for maintaining the living documentation as part of normal engineering work.

21. DOCUMENTATION OWNERSHIP

Documentation is an organizational asset.

It should not depend permanently on one human, one AI model, or one external tool.

Initially, external development tools may help maintain it.

Later, responsibility transfers to the internal Software Engineering Department and other authorized departments.

Each department remains responsible for the correctness of information within its domain, while the Software Engineering Department can maintain overall structural coherence.

22. VERSIONING

The living documentation itself should be versioned through the organization's authoritative data and versioning mechanisms.

The current version must always be easy to identify.

Previous versions should remain recoverable for audit, comparison, and rollback purposes.

Version history should not clutter the main readable document.

The current document should read cleanly as the current truth.

Historical changes should be available separately when needed.

23. CHANGE TRACEABILITY

For important architectural changes, the organization should be able to determine:

- what changed;
- why it changed;
- when it changed;
- what directive or decision caused it;
- who or what approved it;
- what implementation work resulted;
- what tests validated it;
- what previous description it replaced.

This creates a clear connection between governance, engineering, implementation, and documentation.

24. DOCUMENT QUALITY RULE

Every time the living documentation is updated, the editor or agent should ask:

Does the document still make sense as one story?

If the answer is no, the document must be reorganized.

The goal is not to preserve every sentence ever written.

The goal is to preserve every important idea while continually improving clarity.

25. CORE STANDARD

The living documentation shall be:

COHERENT
It must describe one understandable system.

CONSISTENT
Concepts and terminology must agree throughout the document.

CONTINUOUS
It must evolve together with the system.

CURRENT
It must represent the best known present state.

CLEAR
It must use simple, direct language.

COMPLETE ENOUGH
It must contain enough information to understand the architecture and its current state.

TRACEABLE
Important changes must connect back to their reasons and authority.

READABLE
Humans and AI agents must be able to understand it efficiently.

26. TARGET END STATE

The living documentation should eventually allow a new authorized human or AI agent to read the system documentation and understand:

- what Jarvis is;
- why it exists;
- how it is organized;
- how it behaves;
- how it evolves;
- how Parliament drives change;
- how departments interact;
- how agents persist and learn;
- how shared organizational knowledge works;
- how software engineering works;
- what has been implemented;
- what is still being developed;
- what known gaps remain;
- how releases are controlled;
- how rollback works;
- how the organization learns from failures;
- and what stage of maturity the overall system has reached.

The documentation should function as the continuously maintained map of the Jarvis organization.

The system may become complex.

The documentation must make that complexity understandable.
