# CentrAlign AI — Founding Engineer take-home (source: JD)

Company: https://centralign.ai/ · Role: Founding Engineer (remote, full-time)
Deadline: **Oct 12, 2026** · Submission form: https://forms.gle/CeaiXnsQ5oqx4dFx6

## Problem statement: AI Employee / Autonomous Company Operator

Company tasks are spread across websites, desktop apps, documents, and internal systems.
People must find information, follow procedures, and manually complete and check the work.
Short requests often leave the required steps and company context unstated.
AI-generated answers alone do not complete these tasks.

We are building an **AI operator that turns a company request into completed work.**
It should use company context to identify the right sources, procedures, and permitted actions.
It should operate browsers, desktop apps, and files using existing tools wherever possible.
It should verify the outcome, return useful evidence, and ask for help when needed.
The goal is **reliable completion of varied company tasks with minimal human supervision.**

## Task

Come up with your vision of the solution and build a working prototype / proof of concept.
Not prescribed: architecture, models, agent framework, language, interface, computer-use technology,
planning architecture, memory implementation, exact workflow.
**A narrow system that genuinely demonstrates autonomy is considerably more valuable than a broad
prototype that only simulates it.**

## They would like to see

- Understanding a user's intended outcome
- Determining what needs to be done
- Planning the required actions
- Selecting appropriate tools
- Executing actions
- Observing what happened
- Determining the next action based on the result
- Recovering from failures where reasonable
- Maintaining relevant state/context
- Asking for human input or approval when required
- Verifying that the requested outcome was actually completed
- Returning evidence or a useful summary of what happened

Core loop: **Goal → Understand → Plan → Execute → Observe → Adapt → Verify → Complete**
(they encourage a different interpretation if better).

## Evaluation criteria

- **Autonomy** — determines and executes meaningful next actions without being told every step
- **Execution** — actually performs work rather than explaining what should be done
- **Reliability** — handles unexpected states, errors, retries, failures
- **Verification** — determines whether the requested outcome was actually achieved
- **Generalization** — how much stays unchanged for a different task
- **Engineering Quality** — architecture, implementation, code quality, debugging, technical judgment
- **Product Thinking** — focuses on the user's actual objective
- **Technical Understanding** — can explain why it was built this way
Not evaluated on the number of features.

## Submission requirements

- GitHub repository or equivalent source link
- README with setup and run instructions
- Short architecture explanation
- Important technical/design decisions
- Demo video or accessible live demo
- Known limitations
- What you would build next with more time
- Assumptions made
- Models, APIs, frameworks, external services, pre-built components used

AI coding tools are allowed; **you must understand the system you submit** and be ready to explain,
debug or modify it in the technical discussion.
**Do not use real company credentials, confidential information, or unauthorized access to third-party
systems. Use sandbox/mock environments.**

## The technical discussion may ask you to

Explain the architecture · walk through it live · explain why the agent made particular decisions ·
debug an issue · modify or extend part of the prototype · discuss reliability and generalisation ·
discuss evolution into a production-grade AI employee. For the Founding Engineer, emphasis is on
architecture, scalability, reliability, security, extensibility and long-term technical decisions.

## What the role works on (context for design choices)

Core AI employee runtime (goals, planning, execution, observation, memory, permissions, approvals,
recovery, verification); agents operating browsers, files, desktop apps, APIs and internal systems;
persistent company memory; reusable tool and connector abstractions; background execution, task queues,
scheduling, retries, human-in-the-loop controls and auditability; learning from company feedback;
reliability when plans fail or environments change.
