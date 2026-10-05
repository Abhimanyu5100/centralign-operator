# Research notes: why each component exists

Condensed from the full research report (kept in claude.ai; export it as Markdown from the doc if you
want the long version in the repo). Each section: the lesson, the evidence, what we build.

## Harness shape — thin, single executor
- **Pointer** (May 2026, 83.6% OSWorld-Verified, above the 72.4% human baseline): feasibility gate →
  planner writing target-state milestones → one executor with every tool. They deleted a router to
  code/GUI/browser sub-agents because hand-offs lost state. https://www.pointer.ai/blog/sota
  - "Two strikes, then switch": two failures of one mechanism → change approach.
  - The "just do it" problem: models keep going on impossible tasks (installed a password cracker, Tor).
  - Roundabout behaviour signals a missing tool; phantom tool calls ≈ 0.5% (`triple_click`).
  - Superscore 90.9% vs 83.6% single run: the remaining gap is variance → verification and guardrails.
  - ~10% of benchmark reference answers were wrong; their own end-state verifier was often the better judge.
- **MAST** (NeurIPS 2025): 14 failure modes, 3 groups; multi-agent systems often barely beat single agents.
  https://arxiv.org/abs/2503.13657
→ We build: gate + planner + single executor; verifier separate.

## Actions — hybrid API, code and GUI
- **Beyond Browsing** (ACL Findings 2025): WebArena browsing-only 14.8%, API-only 29.2%, hybrid 38.9%.
  https://arxiv.org/abs/2410.16464
- **CoAct-1** (ICLR 2026): code as an action; 60.76% OSWorld, 10.15 vs 15 average steps.
  https://arxiv.org/abs/2508.03923
- **UFO2** (Microsoft): unified GUI–API action layer; precondition checks (is_enabled, is_visible) before
  speculative actions; safeguard that pauses on dangerous actions. https://arxiv.org/abs/2504.14603
- **WALT / SkillWeaver**: turn GUI workflows into validated, parameterised tools; SkillWeaver +31.8%
  relative on WebArena. https://arxiv.org/abs/2504.07079
→ We build: one tool registry with a uniform contract (side-effect class, channel, pre/postconditions,
undo); reads via any channel, writes via the audited channel.

## Observation
- **AgentOccam** (ICLR 2025): +26.6 points from cleaning observation and action spaces alone.
  https://arxiv.org/abs/2410.13825
- **Windows Agent Arena**: accessibility tree → Set-of-Marks on screenshot; previous screenshot included.
  https://arxiv.org/abs/2409.08264
- **Screen2AX**: only 33% of macOS apps have complete accessibility metadata (vision fallback matters for
  real desktops). https://arxiv.org/abs/2507.16704
→ We build: pruned a11y tree as compact text + diffs; screenshots on demand.

## Planning
- **Plan-and-Act** (ICML 2025): dynamic replanning +10.31 points; a good plan alone lifted an untrained
  executor by 34.39 points. https://arxiv.org/abs/2503.09572
- **WebDreamer** (TMLR 2025): LLM as world model — simulate "what happens if I click this" before
  committing; motivated by irreversible actions. https://arxiv.org/abs/2411.06559
→ We build: state milestones (DAG, SOP-cited); replan triggers and budget; predict-before-irreversible-write.

## Verification
- **Autonomous Evaluation and Refinement** (COLM 2024): evaluators agree with oracles 74.4–92.9%; as a
  Reflexion reward, +29% relative on WebArena. https://arxiv.org/abs/2404.06474
- **AgentRewardBench**: best LLM judges ≈ 70% precision; rule checks under-report success; judge on
  success, **side effects**, repetition. https://arxiv.org/abs/2504.08942
- **GUI-Critic-R1** (NeurIPS 2025): pre-operative critic catches errors before execution.
  https://arxiv.org/abs/2506.04614
- **Agent S3 / Behavior Best-of-N**: behavior narratives (what was done, what changed) as the unit of
  judgement. https://arxiv.org/abs/2510.02250
→ We build: postconditions → milestone predicates (different channel) → side-effect DB diff →
fresh-context judge listing unmet criteria. Verifier owns status.

## Reliability and recovery
- **τ-bench** (ICLR 2025): policy docs + state-checked success; **pass^k** — GPT-4o ≈ 61% pass^1 retail,
  < 25% pass^8. https://arxiv.org/abs/2406.12045
- **GoEX** (Berkeley Gorilla): undo + damage confinement make post-facto validation possible.
  https://arxiv.org/abs/2404.06921
→ We build: typed failure classifier with per-class budgets; compensating actions (saga); checkpoints.

## Safety, policy, asking
- **ST-WebAgentBench** (ICLR 2026): Completion Under Policy < 2/3 of raw completion; policy hierarchy
  Organization > User > Task. https://arxiv.org/abs/2410.06703
- **CaMeL** (Google DeepMind): privileged planner never reads untrusted data; quarantined extractor has
  no tools; provenance-checked tool calls; 77% vs 84% undefended on AgentDojo with provable security.
  https://arxiv.org/abs/2503.18813
- **Learning to Ask** (EMNLP 2025): agents invent missing arguments. https://arxiv.org/abs/2409.00557
- **Ambig-SWE**: interaction lifts underspecified tasks up to 74%. https://huggingface.co/papers/2502.13069
- **Ask Early, Ask Late, Ask Right** (2026): ask rates — GPT-5.2 52%, Claude Sonnet 4.5 23%, Gemini 3
  Flash 0%. → With Gemini as executor, the harness must force asks. https://arxiv.org/abs/2605.07937
→ We build: policy gate in code; provenance tags; mandatory ask when a required field is unknown or ≥ 2
candidates remain.

## Memory and learning
- **Agent Workflow Memory** (ICML 2025): induced workflows +24.6% (Mind2Web) and +51.1% (WebArena)
  relative. https://arxiv.org/abs/2409.07429
- **Pointer Hydra** (Aug 2026): findings typed learning / rule / issue, scoped, evidenced, reversible;
  accuracy 54.4% → 76.8% in three rounds; "more memory does not make a better agent".
  https://www.pointer.ai/blog/self-improvement
→ We build: company knowledge (read-only) · run memory · governed findings (proposed → approved).

## Benchmark design
- **TheAgentCompany**: self-hosted fake company, checkpoints, partial credit
  = 0.5 × checkpoints + 0.5 × full success. https://arxiv.org/abs/2412.14161
→ AcmeBench metrics: success, checkpoint credit, pass^k, CuP, side-effect rate, correct refusals,
ask precision, false-completion rate, cost and time per success.

## Reused from the author's TCS Research internship
Agent archetypes → tool side-effect/latency classes · standardised wrapper → tool registry contract ·
planner DAG → milestone DAG · six-backend memory taxonomy (PM/WM/STM/ENT/EM/SM) → memory stores ·
OTEL latency decomposition → per-run traces · concurrency sweeps → task-queue scaling test ·
embedding routing + deterministic override → tool-subset retrieval.
