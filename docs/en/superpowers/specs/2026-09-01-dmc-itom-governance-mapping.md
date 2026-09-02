# DMC and Digital Project Initiation Policy — ITOM Alignment Mapping

- Status: Confirmed, pending implementation on `feature-local`
- Date: 2026-09-01
- Scope: ITOM requirements, projects, unified investment, reporting, permissions, and audit
- Authoritative policies: the two 2026-09-01 Chinese DOCX policies supplied by the user

## 1. Conclusion

The two policies are compatible with ITOM's product position. ITOM remains a governance hub for demand and project records; it does not become the DMC meeting system, financial ledger, procurement/contract system, legal/security approval system, process-design system, or data-governance system.

The policies confirm the five-dimension requirement model:

1. Strategy alignment
2. Business value
3. Technical feasibility
4. Business maturity (organization, people, and process)
5. Risk

The current code still exposes D6 value speed and calls D4 organizational readiness, so new assessments need to converge to five dimensions while preserving historical values read-only without exposing version labels in normal UI.

## 2. Boundary mapping

| Policy requirement | ITOM should hold | Out of ITOM scope |
|---|---|---|
| Annual portfolio and plan | project source, plan year, portfolio reference, DMC authorization snapshot | annual budget ledger and accounting |
| Out-of-plan demand to project | assessment, project classification, decision result, demand-project link | meeting scheduling and professional review execution |
| DMC decision | topic, conclusion, amount, budget source, conditions, owner, deadline, check date, evidence reference | full online voting in the first release |
| Business maturity | organization/people/process notes and score | APQC/process authoring and process execution |
| Investment authorization | external investment basis and approval level | procurement, contracts, and payment accounting |
| Professional approvals | external status, reference, link, summary, and attachment reference | the professional approval itself |
| Project lifecycle | budget pending, start, acceptance, observation, value review, closure | detailed professional execution facts |
| Management reporting | DMC quarterly, half-year, annual, and portfolio views | professional-system master reports |

## 3. Gaps and adaptation

| Capability | Current baseline | Required adaptation |
|---|---|---|
| Requirement scoring | `requirement_scoring.py`, `Requirement`, and `RequirementScore` use D1-D6 | use five dimensions for new records; preserve old fields read-only, rename D4 semantics, stop requiring D6 |
| Scoring configuration | weights, thresholds, rubric, and role weights are configurable | default D1 20%, D2 20%, D3 20%, D4 30%, D5 10%; do not mix monetary and effort thresholds |
| Requirement-to-project | `Requirement.project_id` and `implementation_route` exist | add annual/out-of-plan source, classification reason, and decision reference |
| Project model | portfolio, budget, planned/actual dates, manager, and status exist | add source, plan year, decision level, budget state, external authorization amount, phase/observation fields |
| Unified investment | already separates lifecycle, category, internal/external labor, CAPEX/OPEX, and worklogs | keep one ledger; separate external authorization from internal labor and run cost in aggregation |
| Report Center | already covers project, requirement, operations, people, process, platform, and formal reports | add DMC decisions, out-of-plan conversion, budget-pending, observation, and value-review metrics |
| DMC record | no first-class decision snapshot/signature matrix is present | add an optional governance-record layer; record offline decisions manually before considering online voting |

## 4. Governance rules to implement

### Requirement assessment

Use the five dimensions above. D4 business maturity combines organization, people, and process. A suggested rubric is:

- 1: no clear business owner, unclear responsibilities, and no usable process;
- 2: a partial owner or process exists, but cross-functional responsibilities and key steps are unclear;
- 3: ownership and the main process are defined enough to bound implementation, but details remain;
- 4: owner, participants, process steps, inputs/outputs, and exception handling are substantially defined;
- 5: owner and resource commitment exist, and the process is detailed enough for system design, data definition, and acceptance.

The policy requires a complete out-of-plan application package (problem, expected result, owner, resources, boundary/risk, and maturity). This is intake completeness, not a mandatory D1/D2 evidence upload. D1/D2 evidence remains recordable but optional.

### Two-track initiation

```text
Annual plan: annual portfolio review → DMC approval = initiation/authorization → budget → start

Out of plan: demand → five dimensions → project classification → amount/impact decision
            → authorized decision-maker or DMC → budget → project start
```

Project classification must cover a new/replacement system, external IT services, internal effort of at least 20 person-days, an independent budget, a detailed plan, or an independent project owner. Smaller work remains an ordinary requirement, operations ticket, or development task.

### Decision thresholds

| External authorization amount | Decision level |
|---:|---|
| ≤ CNY 300,000 | digital team evaluates; digital leader decides and reports to DMC |
| > CNY 300,000 and ≤ CNY 1,000,000 | digital leader evaluates; Eason decides, with optional DMC escalation |
| > CNY 1,000,000 | direct DMC decision |

Authorization amount includes external software, hardware, cloud, consulting, and implementation only. Internal labor, administration, and post-go-live operations remain reportable investment facts but are not mixed into the authorization amount.

### Lifecycle and signatures

Record budget pending, start, stage acceptance, go-live, observation, value review, operations handover, and closure. Default observation is at least three months for amounts over CNY 1,000,000 and at least one month otherwise. Annual-plan and out-of-plan projects use different signer matrices but preserve signer, role, time, conclusion, and evidence snapshots.

## 5. Phased delivery

### P0 — minimum policy-compatible loop

1. Converge requirement scoring to five dimensions and rename D4 to Business maturity.
2. Add in-plan/out-of-plan source and a project-classification checklist.
3. Add configurable CNY 300,000/CNY 1,000,000 thresholds, separate from effort threshold.
4. Add DMC decision records with escalation reason, conditions, owner, deadline, and check date.
5. Preserve requirement, assessment, and decision snapshots when converting to a project.

### P1 — project governance and investment semantics

Add budget-pending, stage acceptance, observation, value review, handover, authorization-versus-TCO aggregation, signer matrices, external approval references, and minimum-permission/audit events.

### P2 — reporting and controlled references

Add DMC quarterly, half-year, annual, out-of-plan conversion, overdue decision, budget variance, observation, and value-realization reports. Add read-only or controlled summaries from finance, procurement, process, security, and data systems only when each connector is separately specified and authorized.

## 6. Acceptance matrix

| Goal | Evidence |
|---|---|
| new requirements use five dimensions | backend, API, frontend, and compatibility tests |
| D4 reflects organization/people/process maturity | rubric, examples, and API snapshot |
| history is not rewritten | migration/read tests and read-only UI verification |
| two project tracks are distinguishable | project creation, conversion, and filter tests |
| threshold boundaries are correct | boundary unit tests and decision-record tests |
| authorization and internal labor are separated | unified-investment aggregation and report assertions |
| offline DMC decisions are traceable | decision, signer, audit, and evidence-reference tests |
| observation and value review are traceable | lifecycle API and report tests |
| professional boundaries remain intact | permission and no-generic-write regression tests |

## 7. Documentation impact

When implementation starts, assess and update `README.md`, the Chinese and English PRD, data-model, API/architecture, and identity/organization documents in the same delivery. This mapping is an analysis artifact and does not change runtime contracts, so the formal product/data/API documents should be updated after P0 implementation and focused tests pass.

## References

- [ADR-0001](../../adr/0001-platform-product-operations-overlay.md)
- [ADR-0002](../../adr/0002-dmc-project-governance-alignment.md)
- [Platform Product Operations Hub specification](2026-08-31-platform-product-operations-hub-design.md)
