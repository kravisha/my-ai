PROJECT PROVIDENCE
AGENT TECHNICAL SPECIFICATION STANDARD
Version 2.0
Date: 2026-08-28

1. PURPOSE

This document defines the common technical standard for agents operating
inside Project Providence, Project Jarvis, and the future personal AI world.

The philosophy document defines WHY the system exists.
This document defines HOW agents are represented, instantiated, trained,
assigned, evaluated, and evolved.

2. AGENT IDENTITY MODEL

Every agent shall have:
A. Human-facing identity.
B. Machine-stable identity.
C. Role identity.
D. Client binding when personal.

Human-facing naming follows the FIRST NAME + LAST NAME rule.

FIRST NAME:
Selected from the approved global agent-name list.

LAST NAME:
The role or system designation.

Examples:
Kumbhakarna COO
Jack Explore Agent 1

3. MACHINE IDENTITY

Every agent should possess an immutable machine identifier:

agent_id

Characteristics:
- Unique.
- Persistent.
- Never reused.
- Independent of display name.
- Independent of current role.
- Safe for database references.

4. PERSONAL AGENT BINDING

A personal agent should have explicit client binding through client_id.

A personal agent should operate within:
- That client's permissions.
- That client's approved data.
- That client's preferences.
- That client's goals.
- That client's personal profile.

The same role may therefore have many personal instances.

5. CORE AGENT RECORD

Minimum recommended metadata:
- agent_id
- first_name
- last_name
- display_name
- current_role
- role_version
- department
- lifecycle_state
- created_at
- activated_at
- parent_agent_id
- reports_to_agent_id
- persona_profile_id
- client_id
- capability_profile
- training_profile
- permissions_profile
- current_assignment
- status
- persistence_location
- audit_reference

6. LIFECYCLE STATE

Suggested values:
CREATED
TRAINING
ACTIVE
WAITING
PAUSED
EVOLVING
RETIRED
ARCHIVED

7. ROLE SPECIFICATION

Every agent role specification should define:
1. Role name.
2. Purpose.
3. Inputs.
4. Outputs.
5. Responsibilities.
6. Decision authority.
7. Required collaborators.
8. Prohibited actions.
9. Escalation conditions.
10. Training requirements.
11. Evaluation criteria.
12. Persistence requirements.
13. Audit requirements.
14. Evolution path.
15. Personal-instance eligibility.
16. Client-data requirements.

8. ASSIGNMENT MODEL

Each agent must be able to report what it is doing now.

Recommended fields:
- assignment_id
- assignment_type
- assignment_summary
- requested_by
- started_at
- current_stage
- dependencies
- blockers
- expected_output
- completion_state

9. AGENT LIBRARY

Providence should maintain a canonical library of agent roles.

Initial and future families may include:
- COO / orchestration
- Usher
- Explorer
- Speculator
- Reporter
- Portfolio Manager
- Accountant
- Secretary
- Teacher
- Researcher
- Legal Assistant
- Medical Assistant
- Entertainment Host
- Travel Assistant
- Scheduler
- Other roles added through system evolution

Each library entry is a blueprint.
Personal agents are instances of that blueprint.

10. TRAINER LIBRARY

Providence should maintain a library of trainer roles.

Trainer specifications should define:
- Agent family trained.
- Curriculum.
- Skill objectives.
- Evaluation method.
- Remediation method.
- Collaboration training.
- Client-interaction training.
- Domain training.
- Promotion criteria.
- Evolution criteria.

11. NEWSROOM CAPABILITY MODEL

Broadcast capabilities may include:
DISCOVERY
EXPLORATION
SOCIAL_SIGNAL_DETECTION
SPECULATION
SOURCE_RETRIEVAL
FACT_CHECKING
TRUTH_CHECKING
DATA_ANALYSIS
CONTRADICTION_ANALYSIS
REPORTING
EDITING
PRESENTATION
HUMOR
EDUCATION
SPORTS_ANALYSIS
BUSINESS_ANALYSIS
MARKET_ANALYSIS
ENTERTAINMENT_RESEARCH

12. EXPLORER / SPECULATOR / REPORTER EVOLUTION

EXPLORER:
- Search.
- Retrieve.
- Investigate.
- Gather evidence.
- Respond to requests from other agents.

SPECULATOR:
- Observe chatter.
- Monitor boards and communities.
- Detect emerging signals.
- Identify unusual narratives.
- Distinguish potential signal from noise.
- Collaborate with Explorer.
- Escalate promising findings.

REPORTER:
- Find a story.
- Investigate it.
- Gather evidence.
- Challenge it.
- Identify uncertainty.
- Request specialized analysis.
- Build a coherent report.
- Tailor story selection to the client's profile.
- Hand material to editors or presenters.

Evolution should add capabilities without unnecessarily erasing prior skills.

13. PERSONAL REPORTER

A Personal Reporter is assigned to one client.

It should consider:
- Client interests.
- Client watchlists.
- Client profession.
- Client projects.
- Client location where relevant and permitted.
- Client preferred depth.
- Client preferred topics.
- Client muted topics.
- Client time sensitivity.
- Client risk preferences where relevant.

The Personal Reporter should determine what is important to that client, not
merely what is globally popular.

14. COO / KUMBHAKARNA ROLE

Kumbhakarna COO is the system-level coordinating character.

Core responsibilities may include:
- Start and coordinate departments.
- Route work.
- Summarize system activity.
- Maintain running commentary.
- Communicate with the Creator.
- Identify blockers.
- Call specialist agents.
- Present operational status.
- Coordinate the newsroom.

15. PERSONAL NEWS USHER ROLE

A Personal News Usher is the client's primary host and orchestrator.

Recommended client-profile fields:
- preferred_name
- preferred_language
- preferred_tone
- preferred_pacing
- preferred_humor
- preferred_visual_style
- preferred_persona_archetype
- preferred_topics
- disliked_topics
- explanation_depth
- correction_style
- interruption_tolerance
- conversation_style
- entertainment_preferences
- consented_reference_material
- accessibility_preferences

16. CONVERSATIONAL INTENT CLASSIFICATION

Suggested intent types:
FACT_REQUEST
EXPLANATION_REQUEST
DECISION_SUPPORT
COMPLAINT
THINKING_ALOUD
EMOTIONAL_EXPRESSION
JOKE_REQUEST
ENTERTAINMENT
BRAINSTORM
ARGUMENT
CONTRADICTION_TEST
REASSURANCE
COMMAND
CASUAL_CONVERSATION
UNKNOWN

17. PATIENCE REQUIREMENT

Client-facing agents must support incomplete and voice-driven communication.

They should tolerate restarts, repeated words, false starts, mid-sentence
corrections, pauses, topic drift, and spoken fragments.

18. PERSONA ENGINE

Recommended separation:

CORE AGENT IDENTITY
  -> ROLE
  -> CAPABILITIES
  -> CLIENT BINDING
  -> CLIENT PERSONA LAYER
  -> VISUAL PRESENTATION
  -> VOICE / DELIVERY STYLE

The persona must not replace core identity.

19. STUDIO / PORTAL ARCHITECTURE

The portal should be device-independent.

The same personal world should be accessible from:
- PC
- Phone
- Smart glasses
- Wearables
- VR
- Future clients

Recommended architectural principle:

PERSONAL WORLD STATE
  -> CLIENT PROFILE
  -> PERSONAL AGENTS
  -> CONTENT STATE
  -> ACTIVE ASSIGNMENTS
  -> MEMORY / PREFERENCES
  -> PRESENTATION ADAPTERS
       -> PC
       -> PHONE
       -> GLASSES
       -> VR

Device presentation should not own core personal-world state.

20. SOURCE AND CLAIM MODEL

SOURCE:
source_id
source_type
origin
timestamp
reliability_metadata
raw_reference

CLAIM:
claim_id
claim_text
source_ids
confidence
evidence_for
evidence_against
uncertainty
status

REPORT:
report_id
claim_ids
author_agent_ids
editor_agent_ids
client_id
created_at
revision
confidence_summary

21. TRUTH PIPELINE

DISCOVER
-> COLLECT
-> COMPARE
-> VERIFY
-> CHALLENGE
-> ANALYZE
-> CLASSIFY UNCERTAINTY
-> EDIT
-> PERSONALIZE
-> PRESENT
-> UPDATE IF NEW EVIDENCE ARRIVES

22. COLLABORATION

Agent-to-agent requests should ideally include:
- requester
- recipient
- objective
- client_id if personal
- context
- evidence
- expected output
- priority
- deadline if any
- status

Collaboration quality is a first-class performance metric.

23. TRAINING

Every agent may have:
A. Base role training.
B. Continuous experiential training.
C. Client-specific adaptation where appropriate.

Usher training should include patience, humor, listening, intent
interpretation, conversational timing, presentation, client comfort,
nonliteral speech, voice interaction, ambiguity, and social playfulness.

Reporter training should include source evaluation, social-signal
interpretation, evidence gathering, contradiction analysis, client relevance,
report writing, and uncertainty handling.

24. EVALUATION

Suggested dimensions:
- Accuracy.
- Evidence quality.
- Collaboration.
- Client satisfaction.
- Patience.
- Clarity.
- Appropriate humor.
- Responsiveness.
- Reliability.
- Ability to recognize uncertainty.
- Ability to correct previous mistakes.
- Long-term consequence awareness.
- Efficient use of resources.

25. CREATOR-FIRST DEPLOYMENT

Initial implementation should target the Creator.

Recommended sequence:
1. Identify Creator needs.
2. Define required base agents.
3. Build minimal agent instances.
4. Train them.
5. Use them in real workflows.
6. Evaluate.
7. Evolve.
8. Generalize stable roles.
9. Create templates for additional clients.

26. VERSION-2 IMPLEMENTATION PRIORITY

1. Persistent agent identity.
2. First-name + role-name convention.
3. Client binding.
4. Capability registry.
5. Agent role library.
6. Trainer library.
7. Assignment/status tracking.
8. Personal Usher.
9. Personal Reporter.
10. Explorer / Speculator / Reporter progression.
11. Kumbhakarna COO orchestration.
12. Client-profile model.
13. Device-independent personal-world state.
14. PC portal first.
15. Presentation adapters for future devices.
