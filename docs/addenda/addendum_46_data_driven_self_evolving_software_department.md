DATA-DRIVEN SELF-EVOLVING SOFTWARE ENGINEERING DEPARTMENT

1. PURPOSE

The Software Engineering Department is the internal engineering capability of the Jarvis organization.

Its ultimate purpose is to make the organization technologically self-reliant.

During the initial construction of Jarvis, external development capability such as Claude Code may be used because the organization does not yet possess a mature internal software department.

This dependency is intentionally temporary.

The organization will progressively:

1. Create its internal Software Engineering Department.
2. Train that department using increasingly difficult engineering work.
3. Transfer development responsibilities from Claude Code to the internal department.
4. Validate the department during simulation and historical-data phases.
5. Reach complete internal engineering capability.
6. Perform comprehensive QA and UAT.
7. Declare the system production-ready.
8. Enter live operation without requiring Claude Code or another external developer to maintain or evolve the organization.

The desired end state is:

Jarvis develops Jarvis.

The organization becomes capable of understanding its own architecture, implementing authorized changes, testing those changes, learning from outcomes, improving its engineering practices, and continuously evolving itself.

2. FUNDAMENTAL ARCHITECTURAL PRINCIPLE

Jarvis is not intended to be a conventional application whose organizational behavior is buried permanently inside program code.

The fundamental architecture is:

Stable machinery, evolving data.

Code provides the mechanisms.

Data provides the current behavior.

Where practical, the following must exist outside hard-coded program logic:

- priorities
- objectives
- policies
- procedures
- strategies
- organizational philosophy
- operating rules
- departmental mandates
- agent instructions
- authority structures
- training material
- lessons learned
- approved practices
- evaluation criteria
- thresholds
- workflows
- behavioral directives
- organizational knowledge
- current operating assumptions

These artifacts become governed organizational data.

Changing an organizational rule therefore should normally mean changing governed data rather than rewriting software.

3. DATA-DRIVEN BEHAVIORAL CHANGE

The guiding analogy is human organizational behavior.

When a government passes a law, citizens do not require biological reconstruction before following the new law.

When a company changes a procedure, employees do not need to be rebuilt.

They receive new information, understand it, and alter their behavior.

Agents should operate similarly.

An agent may:

1. Read new information.
2. Interpret it.
3. Incorporate it into its operating context.
4. Modify its decisions and behavior accordingly.

Therefore:

A behavioral change does not automatically imply a software change.

For example, Parliament might determine:

"The current procedure is creating disorder. From now on all departments must submit requests in this format and follow this approval sequence."

That resolution becomes governed organizational data.

Agents subsequently retrieve the current authoritative rules and follow the new procedure.

No agent executable needs to be rewritten merely to adopt the policy.

4. KNOWLEDGE AND GOVERNANCE LAYER

The application shall contain an authoritative organizational knowledge and governance layer.

It may physically use one or more databases, document stores, encrypted files, vector stores, or other storage technologies.

The physical technology is secondary.

Conceptually it represents the organization's living operating knowledge.

It should contain, where appropriate:

4.1 Constitution

The highest-level organizational principles and limits.

4.2 Laws and Parliamentary Resolutions

Approved organization-wide directives.

4.3 Policies

Standing operating requirements derived from higher-level authority.

4.4 Procedures

Specific methods for performing recurring activities.

4.5 Strategies

Current approaches selected to achieve organizational objectives.

4.6 Priorities

Current ordering of organizational goals.

4.7 Knowledge

Facts, research, institutional experience, reference material, books, reports, findings, and other learning material.

4.8 Training Material

Material intended specifically to improve agent capabilities.

4.9 Lessons Learned

Experience generated from simulation, historical testing, production operations, failures, successes, evaluations, and postmortems.

4.10 Agent and Department Directives

Instructions applicable to specific roles, departments, or situations.

5. AUTHORITY HIERARCHY

Data-driven behavior must not mean that every piece of data has equal authority.

The system must understand precedence.

A conceptual hierarchy is:

1. Constitution
2. Constitutional amendments
3. Parliamentary laws/resolutions
4. Organization-wide policies
5. Department policies
6. Approved procedures
7. Current strategies
8. Operational directives
9. Project instructions
10. Knowledge/reference material
11. Historical observations
12. Suggestions and unapproved proposals

Lower-level material cannot silently override higher-level authority.

Conflicts must be detected and escalated through the organizational governance process.

6. PARLIAMENT AS THE SOURCE OF AUTHORIZED CHANGE

Parliament governs significant organizational change.

A proposed change may originate from:

- an agent
- a department
- an evaluator
- Operations
- the Department of Evolution
- observed system performance
- simulation results
- historical analysis
- failures
- user requirements
- research
- changing external conditions
- another authorized source

A proposal becomes authoritative only through the appropriate governance process.

When Parliament approves a resolution, it becomes an actionable directive.

The Software Engineering Department does not decide organizational ideology.

Its responsibility is to translate authorized intent into a technically sound implementation.

7. SOFTWARE DEPARTMENT MISSION

The Software Engineering Department shall:

- receive approved technical directives;
- understand the requested outcome;
- analyze the existing system;
- determine whether a software change is actually required;
- prefer data-driven implementation when possible;
- design necessary changes;
- implement changes;
- maintain the organizational knowledge architecture;
- maintain data structures and schemas;
- build and maintain internal engineering tools;
- perform testing;
- perform peer review;
- perform integration testing;
- run changes in sandbox/staging environments;
- evaluate compatibility;
- prepare releases;
- create rollback capability;
- document changes;
- monitor outcomes;
- learn from failures and successes;
- improve its own engineering competence over time.

8. DATA CHANGE BEFORE CODE CHANGE

For every directive, the Software Department must first determine:

Can the desired result be accomplished through governed data?

The preferred order is:

Level 1: Knowledge Change
Add or improve knowledge available to agents.

Level 2: Directive / Policy Change
Alter agent behavior through an approved instruction or rule.

Level 3: Configuration Change
Modify configurable behavior, thresholds, workflows, permissions, routing, or operational parameters.

Level 4: Capability Composition
Achieve the requirement by combining existing capabilities differently.

Level 5: Software Change
Modify or add program logic only when the existing architecture genuinely lacks the mechanism required to perform the requested function.

This hierarchy prevents unnecessary code proliferation.

9. SOFTWARE DEPARTMENT AGENT MODEL

The Software Department should not begin with a large collection of narrowly specialized permanent agents.

Instead it uses:

One primary general-purpose Software Engineer agent type.

Each instance should be capable of multiple engineering functions.

Possible temporary roles include:

- project manager
- architect
- developer
- database engineer
- knowledge-base engineer
- reviewer
- tester
- QA engineer
- release engineer
- investigator
- documentation engineer

Roles describe responsibilities.

They do not necessarily describe different agent implementations.

10. MINIMUM PERMANENT HEADCOUNT

The department should maintain the minimum number of persistent agents necessary for continued operation.

Additional Software Engineer agents are spawned when workload requires them.

Therefore:

Work determines staffing. Staffing does not determine work.

For a trivial task, one agent may be sufficient.

For a larger task, several instances of the same general Software Engineer type may be spawned.

Example:

- Agent A: project/design owner
- Agent B: implementation
- Agent C: independent review/testing

For a more complex program:

- one coordinating agent
- several implementation agents
- one or more independent validation agents

When the workload falls, unnecessary temporary agents can be released.

11. SEPARATION OF RESPONSIBILITY WITHOUT AGENT PROLIFERATION

Governance does not require dozens of specialized agent classes.

It requires independent responsibility.

The same Software Engineer agent type can therefore occupy different roles in different instances.

However, for significant changes:

The agent that produces a change should not be the sole authority that approves the same change.

This provides peer review without creating an unnecessarily complicated organizational chart.

12. PROJECT MANAGER FUNCTION

The Project Manager is initially a role, not necessarily a permanent unique agent type.

When Parliament passes a directive requiring engineering action:

1. A Software Engineer instance assumes project ownership.
2. It becomes the Project Manager for that directive.
3. It interprets the parliamentary requirement.
4. It identifies affected systems.
5. It creates an implementation plan.
6. It determines required resources.
7. It requests/spawns additional agents when necessary.
8. It coordinates implementation.
9. It ensures testing and review occur.
10. It prepares the project for release approval.

If future workload demonstrates that continuous project-management activity exists, a persistent Project Manager instance may be justified.

This should emerge from actual operational demand rather than be imposed prematurely.

13. DIRECTIVE-TO-IMPLEMENTATION PIPELINE

Observation / Need
↓
Recommendation
↓
Analysis
↓
Parliamentary consideration
↓
Approved Directive
↓
Software Department intake
↓
Project Manager assignment
↓
Requirement interpretation
↓
Existing-capability assessment
↓
Data-change-first assessment
↓
Design
↓
Implementation
↓
Developer validation
↓
Independent review
↓
Automated testing
↓
Sandbox execution
↓
Integration testing
↓
Evaluation
↓
Release candidate
↓
Approval
↓
Scheduled release
↓
Post-release observation
↓
Success / modification / rollback
↓
Lessons learned
↓
Organizational knowledge updated

This forms a closed evolutionary loop.

14. SANDBOX ENVIRONMENT

The system shall contain a sandbox environment.

The sandbox exists so changes can be evaluated without affecting the operating organization.

The sandbox should support:

- cloned organizational state;
- representative datasets;
- simulated agents;
- proposed policies;
- proposed knowledge changes;
- proposed configuration changes;
- proposed software changes;
- synthetic workloads;
- regression tests;
- failure injection;
- behavioral comparison;
- performance comparison.

The sandbox is therefore not simply a software test environment.

It is an organizational experimental environment.

15. BUILT ENVIRONMENT AND BUILD ENVIRONMENT

Build Environment

The environment in which future versions and changes are created and tested.

Built Environment

The currently approved operational organization.

The built environment can continue operating while the Software Department prepares future changes.

This allows continuous engineering without continuously disrupting the operating organization.

16. RELEASE MODEL

Engineering work may occur continuously.

Production changes do not need to occur continuously.

A release candidate can accumulate until the designated release condition or release window.

Conceptually:

Running Version N

continues operating while

Version N+1

is designed, implemented, tested, and prepared.

When N+1 satisfies release requirements:

1. Complete final validation.
2. Capture current database state.
3. Establish rollback checkpoint.
4. Quiesce operations where necessary.
5. Apply the approved release.
6. Validate startup.
7. Perform smoke tests.
8. Resume normal operations.
9. Monitor the new state.
10. Roll back if acceptance criteria fail.

Future architecture may allow hot reload for purely behavioral/data updates where safe.

17. DATABASE-CENTRIC VERSIONING

The authoritative evolution history shall be recorded in the database.

Versioned data should include where appropriate:

- constitution
- laws
- policies
- procedures
- prompts
- directives
- configuration
- priorities
- agent operating instructions
- departmental structures
- workflow definitions
- knowledge artifacts
- training material
- evaluation criteria
- model selection parameters
- system state relevant to behavioral evolution

Each change should retain sufficient provenance to answer:

- What changed?
- Why did it change?
- Who proposed it?
- What evidence supported it?
- Who approved it?
- When did it become active?
- What previous version did it replace?
- What systems or agents does it affect?
- What tests were performed?
- What were the results?
- What happened after release?

18. ROLLBACK

Rollback shall be treated as a fundamental capability rather than an emergency improvisation.

Before significant releases, the system creates an identifiable restoration point.

If the change performs outside approved tolerances:

1. Operations identifies the problem.
2. Release state is marked unhealthy.
3. The authoritative database version is restored or the affected change set is reversed.
4. Agents reload the previous authorized organizational state.
5. Services return to the last known-good condition.
6. The failed release is preserved for analysis.
7. A postmortem is generated.
8. Lessons learned enter organizational knowledge.

Nothing about rollback should erase history.

A rolled-back version remains part of organizational memory.

19. INITIAL CREATION OF THE SOFTWARE DEPARTMENT

The Software Department will itself initially be created with assistance from Claude Code.

Claude Code is therefore effectively an external engineering consultant during the organization's infancy.

The initial implementation should provide the department with:

- repository access appropriate to its duties;
- architecture documentation;
- database access appropriate to its duties;
- development tools;
- test tools;
- sandbox access;
- issue/task management;
- version-control capability;
- build capability;
- deployment tooling;
- logs and observability;
- knowledge retrieval;
- documentation generation;
- agent spawning capability;
- evaluation capability;
- rollback mechanisms.

The critical goal is not merely to create coding agents.

It is to create an engineering organization capable of running its own engineering lifecycle.

20. BOOTSTRAP TRAINING STRATEGY

The Software Department must not immediately be given the hardest task in the organization.

It will mature progressively.

Training occurs through actual engineering work.

The progression should resemble professional development inside a human engineering organization.

21. PHASE 1: TRIVIAL TASKS

After the department is instantiated, it receives deliberately simple assignments.

Examples:

- change a harmless configuration value;
- add a field to a noncritical data structure;
- modify a report format;
- update documentation;
- add a small knowledge artifact;
- modify a simple agent instruction;
- create a trivial validation rule;
- add logging;
- create a basic test;
- repair a deliberately simple defect.

The purpose is not productivity.

The purpose is to teach the department the correct engineering habits.

Evaluation should emphasize:

- understanding requirements;
- following procedure;
- design quality;
- communication;
- collaboration;
- testing;
- documentation;
- proper approval;
- correct release handling;
- rollback preparedness.

22. PHASE 2: SMALL INTEGRATED TASKS

Once trivial work is consistently successful, assignments become larger.

Examples:

- coordinated configuration changes;
- database migration exercises;
- multi-agent workflow changes;
- small feature additions;
- new evaluation metrics;
- small API additions;
- simple cross-department integrations;
- knowledge-base restructuring.

The department learns how changes propagate across systems.

23. PHASE 3: MODERATE ENGINEERING PROJECTS

The department begins receiving projects requiring:

- architecture decisions;
- multiple Software Engineer instances;
- project coordination;
- peer review;
- integration testing;
- release planning;
- rollback planning;
- performance analysis.

At this stage the organization can begin transferring meaningful work away from Claude Code.

24. PHASE 4: COMPLEX SYSTEM WORK

The department eventually receives complex projects involving:

- multiple organizational components;
- new internal capabilities;
- major data-model changes;
- performance optimization;
- infrastructure changes;
- reliability improvements;
- sophisticated agent coordination;
- system-wide migrations.

Claude Code may still be available as a consultant during this period, but it should increasingly become the exception.

25. PROGRESSIVE INSOURCING

The transition away from Claude Code must be deliberate and measurable.

Initially:
Claude Code: almost all engineering
Internal Department: training and trivial work

Later:
Claude Code: complex work
Internal Department: routine work

Later:
Claude Code: difficult exceptions and consultation
Internal Department: majority of work

Later:
Claude Code: independent verification or emergency assistance only
Internal Department: virtually everything

Finally:
Claude Code: no operational dependency
Internal Department: full engineering responsibility

This is the organization's engineering independence curve.

26. SIMULATION PHASE

The Software Department develops primarily inside simulation before production.

Simulation provides large quantities of engineering experience without production consequences.

The system can intentionally generate:

- bugs;
- feature requests;
- changing priorities;
- incompatible requirements;
- performance problems;
- policy changes;
- bad releases;
- database failures;
- integration failures;
- conflicting directives;
- ambiguous requirements;
- rollback events.

The Software Department must respond using normal organizational procedures.

The objective is not to produce perfect results immediately.

The objective is to develop competence through repeated experience.

27. HISTORICAL-DATA PHASE

Historical-data operation creates a stronger test.

The organization processes historical conditions as though they were occurring in real time.

Engineering requirements may arise because the historical organization encounters:

- changing market conditions;
- strategy failures;
- operational problems;
- unexpected workloads;
- missing capabilities;
- data anomalies;
- new requirements.

The Software Department must support the evolving organization without knowing future historical outcomes.

This tests whether engineering processes work under realistic changing conditions.

28. LEARNING LOOP

Every engineering task becomes training data.

For every project, capture:

Input
What was requested?

Interpretation
How was the requirement understood?

Design
What approach was chosen?

Execution
What was actually changed?

Validation
What testing was performed?

Outcome
Did it work?

Operational Effect
Did the change improve the system?

Problems
What failed or nearly failed?

Review
What would experienced engineers do differently?

Lesson
What should future Software Engineer agents know?

These lessons become part of the department's institutional memory.

29. TRAINING IS DATA-DRIVEN

Improving the Software Engineer agent should not necessarily mean modifying its source code.

Its engineering capability should improve through:

- better knowledge;
- accumulated experience;
- procedures;
- examples;
- postmortems;
- architecture documentation;
- coding standards;
- testing standards;
- lessons learned;
- evaluation feedback;
- successful patterns;
- known anti-patterns.

Conceptually:

The Software Engineer reads, experiences, learns, and behaves differently.

This is the same data-driven behavioral model used throughout the organization.

30. MEASURING SOFTWARE DEPARTMENT MATURITY

The department needs measurable competence.

Possible metrics include:

- task completion rate;
- first-pass success rate;
- regression rate;
- defect escape rate;
- rollback frequency;
- test coverage;
- requirement interpretation accuracy;
- architecture compliance;
- average rework;
- independent-review findings;
- release success;
- recovery performance;
- ability to handle task complexity;
- amount of external assistance required;
- collaboration quality.

Task difficulty should increase only when performance supports advancement.

31. COMPLEXITY LADDER

Each engineering task receives a complexity classification.

Level 0
Documentation or harmless data change.

Level 1
Simple isolated implementation.

Level 2
Small multi-component change.

Level 3
Moderate architectural change.

Level 4
Complex system-wide project.

Level 5
Critical platform or architectural evolution.

Progression through these levels becomes evidence of engineering maturity.

32. EXTERNAL-DEPENDENCY METRIC

A particularly important metric is:

External Engineering Dependency

For each project record:

- Was Claude Code required?
- Why?
- At what stage?
- What capability was missing internally?
- Could the internal department learn that capability?
- Did subsequent projects still require external assistance?

The desired trajectory is:

High → Moderate → Low → Exceptional → Zero

33. SELF-RELIANCE MILESTONE

Jarvis reaches the Engineering Self-Reliance Milestone when the Software Department can reliably perform the complete engineering lifecycle:

1. Receive a directive.
2. Understand the requirement.
3. Analyze the system.
4. Determine whether data or software modification is needed.
5. Design the solution.
6. Implement it.
7. Review it.
8. Test it.
9. Validate it in sandbox.
10. Integrate it.
11. Prepare a release.
12. Release it.
13. Monitor it.
14. Roll it back when required.
15. Diagnose failures.
16. Repair problems.
17. Update organizational knowledge.
18. Learn from the result.

This must occur without essential assistance from Claude Code.

34. CLAUDE CODE EXIT CRITERIA

Claude Code does not leave merely because a calendar date arrives.

It leaves because capability has been transferred.

Exit criteria should include:

- internal department handles required complexity levels;
- repeated successful end-to-end projects;
- no material architectural dependency on Claude Code;
- successful independent bug diagnosis;
- successful independent implementation;
- successful independent testing;
- successful release management;
- successful rollback exercises;
- acceptable reliability metrics;
- complete engineering documentation;
- successful simulation performance;
- successful historical-phase performance;
- external-dependency metric reaches effectively zero.

Once these criteria are satisfied, outside engineering assistance is no longer part of normal operation.

35. FINAL QA PHASE

After the organization believes engineering self-reliance has been achieved, development does not immediately become production.

A dedicated stabilization phase begins.

The system undergoes comprehensive QA including:

- functional testing;
- integration testing;
- regression testing;
- performance testing;
- security testing;
- database integrity testing;
- failover testing;
- rollback testing;
- agent-behavior testing;
- parliamentary directive propagation testing;
- sandbox validation;
- recovery testing;
- long-duration testing;
- simulated failure testing.

Critical defects return to the internal Software Department.

The department must fix them itself.

This final period is also a test of independence.

36. USER ACCEPTANCE TESTING

After technical QA, the organization enters UAT.

The purpose of UAT is to establish that the organization behaves as intended from the user's perspective.

UAT validates not merely individual software features but the complete organizational system.

Questions include:

- Does Parliament work correctly?
- Do directives propagate correctly?
- Do agents interpret them correctly?
- Does behavioral change occur without unnecessary coding?
- Can the organization evolve while retaining order?
- Can Software Engineering implement genuine changes?
- Do approvals work?
- Does versioning work?
- Does rollback work?
- Does institutional learning work?
- Is the organization usable?
- Is it dependable?
- Can it operate without Claude Code?

Only after successful QA and UAT is the bootstrap development phase considered complete.

37. GO-LIVE CONDITION

The system goes live only after:

Internal Software Department established
+
Simulation training completed
+
Historical-data training completed
+
Engineering independence demonstrated
+
Claude Code dependency eliminated
+
Full QA passed
+
UAT passed
=
PRODUCTION GO-LIVE

At that moment the outside builders have finished constructing the organization.

The organization itself has become the builder.

38. POST-GO-LIVE EVOLUTION

After go-live, evolution continues.

However, routine evolution should overwhelmingly occur through:

- new knowledge;
- new evidence;
- changing priorities;
- policies;
- procedures;
- strategies;
- directives;
- configuration;
- institutional learning.

These are data-driven changes.

Software modification remains available to the internal Software Department when genuinely new mechanisms are required, but software change is not the normal mechanism for ordinary organizational adaptation.

This distinction is critical.

The organization should evolve every day without requiring the application to be rewritten every day.

39. EXAMPLE: PARLIAMENTARY BEHAVIORAL CHANGE

Suppose agents currently submit tasks informally.

Evidence shows this creates confusion.

A department recommends structured submissions.

Parliament passes:

All interdepartmental requests shall contain requester, objective, priority, deadline, dependencies, and acceptance criteria.

The resolution is stored as the current authoritative rule.

Agents ingest the new rule.

Their behavior changes.

No software deployment is required if the existing architecture supports governed procedural instructions.

This is data-driven evolution.

40. EXAMPLE: TRUE SOFTWARE CHANGE

Suppose Parliament determines that agents require secure real-time video communication, but the platform contains no video capability whatsoever.

Changing instructions cannot create an underlying video transport.

The Software Department identifies a capability gap.

A genuine software project is opened.

The department:

1. designs the capability;
2. implements it;
3. tests it;
4. independently reviews it;
5. validates it in sandbox;
6. integrates it;
7. prepares rollback;
8. releases it through normal governance.

Once available, policies determining how video communication is used again become data-driven.

Thus:

Code creates capabilities. Data determines how the organization uses those capabilities.

41. SELF-EVOLUTION LOOP

World changes
↓
Organization observes
↓
Agents analyze
↓
Recommendation emerges
↓
Governance evaluates
↓
Parliament authorizes change
↓
Software Department determines implementation mechanism
↓

If existing capability is sufficient:
Governed data changes
↓
Agents assimilate new state
↓
Behavior changes

If a new technical capability is required:
Software project
↓
Design
↓
Build
↓
Review
↓
Sandbox
↓
Test
↓
Release
↓
New capability becomes available
↓
Governed data controls its use
↓
Measure results
↓
Learn
↓
Update institutional knowledge
↓
Repeat

This is the foundation of continuous organizational evolution.

42. DESIGN PRINCIPLE: ORGANIZATION BEFORE APPLICATION

Jarvis should not be designed primarily as an application containing many agents.

It should be designed as:

An organization whose employees happen to be agents.

The application provides the infrastructure through which that organization exists.

Parliament governs.

Departments execute.

Agents work.

Knowledge teaches.

Data communicates organizational state.

Software provides capabilities.

Simulation provides experience.

Evaluation provides feedback.

The Software Engineering Department maintains the machinery.

The organization continually modifies its operating knowledge in response to experience.

43. DESIGN PRINCIPLE: INTERNAL CAPABILITY CREATES INDEPENDENCE

During bootstrap:
External developers build the organization.

During transition:
External developers and internal agents build together.

At maturity:
Internal agents build the organization.

After self-reliance:
The organization builds itself.

Therefore the Software Department is not simply another functional department.

It is the mechanism that ultimately removes the organization's dependence on its original builders.

44. TARGET END STATE

The target is a system in which Jarvis can say, in operational terms:

We observe ourselves.

We understand our performance.

We identify deficiencies.

We propose improvements.

We debate and authorize changes through governance.

We implement those changes using our own engineering capability.

We validate the changes before exposing the operating organization.

We retain every prior state.

We can reverse unsuccessful changes.

We learn from every attempt.

Our behavioral evolution normally occurs through data rather than software reconstruction.

Our software department can create new capabilities when they are truly required.

We no longer depend upon Claude Code to develop us.

At that point Jarvis has moved from being software that was built to becoming a software-based organization capable of participating in its own continued engineering and evolution.
