# ADR-0002: Adapt ITOM to the DMC and Digital Project Initiation Policies with an Additive Governance Record Layer

- Status: Accepted
- Date: 2026-09-01
- Decision owner: ITOM product owner
- Scope: requirement assessment, project initiation, unified investment, reporting, and governance audit
- Authority: the [Chinese ADR](../../adr/0002-dmc-project-governance-alignment.md) is authoritative; this file is its English mirror.

## Context

The finalized 2026-09-01 DMC operating policy and digital project initiation policy define two tracks: annual-plan projects and out-of-plan demand-to-project. They define CNY 300,000 and CNY 1,000,000 external-investment decision boundaries and five assessment dimensions: strategy alignment, business value, technical feasibility, business maturity (organization, people, process), and risk.

ITOM already has requirement scoring, requirement-to-project links, portfolios, unified investment, reporting, workflow audit, and permissions. The current scoring code still contains six-dimension fields, while projects do not yet capture every policy fact such as source track, decision snapshot, budget pending, observation, and signer evidence. ITOM remains a management tool for the Platform Product and Enablement team, not a replacement for DMC, finance, procurement, process, data, security, or architecture systems.

## Decision

Adopt an **additive governance record layer that reuses existing domain facts**:

1. New requirements use five dimensions; D4 is Business maturity and combines organization, people, and process. D6 is historical compatibility only and is not required for new assessment.
2. Do not delete or recalculate historical scores and do not expose score-version labels in normal UI; historical records remain read-only.
3. Require the basic out-of-plan application package (problem, expected result, owner, resources, boundary/risk, maturity), while keeping D1/D2 evidence and attachments recordable but optional.
4. Mark projects as annual-plan or out-of-plan and preserve assessment, classification, decision, and conversion snapshots.
5. Add DMC decision records, amount basis, decision level, conditions, owner, deadline, check date, signers, and external-approval references; do not build full online DMC voting in the first release.
6. Count only external software, hardware, cloud, consulting, and implementation in authorization amount. Report internal labor, management, and post-go-live operations separately.
7. Add budget-pending, stage acceptance, observation, value review, operations handover, and closure records.
8. Reuse the unified investment ledger and Report Center; do not create duplicate ledgers or report centers.
9. Professional systems remain systems of record. ITOM stores controlled references, summaries, and auditable snapshots only.
10. All additions are additive and reuse existing RBAC, data scope, workflow, idempotency, and audit boundaries.

## Alternatives

### T1: Build a full DMC and project-investment system inside ITOM

Rejected. This would duplicate meeting, voting, budget, procurement, and professional approval capabilities and create dual master data.

### T2: Explain the policy only in reports without governance records

Rejected. Reports would lack traceable decision levels, DMC conditions, budget-pending state, signers, and observation facts.

### T3: Additive governance records over existing domain facts

Accepted. This keeps the change controlled, preserves history, satisfies traceability, and retains ITOM's management-tool boundary.

## Consequences

### Positive

- Requirement scoring matches the five-dimensional policy and business maturity covers organization, people, and process.
- Annual projects, out-of-plan demands, investment authorization, and DMC conclusions become traceable.
- Authorization, internal labor, and run cost can be analyzed separately.
- The Report Center can produce DMC quarterly, half-year, and annual management views.
- Professional systems keep authority for their facts.

### Costs and constraints

- Requirement and project models need additive governance snapshots and compatibility fields.
- Offline DMC decisions require manual recording; the first release will not create online-voting evidence.
- Authorization and unified-investment reports must use separate aggregation semantics.
- Budget, signer, observation, and value-review facts add lifecycle and test complexity.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Historical six-dimension scores are recalculated | Preserve old fields/snapshots, separate old/new reads, add regression tests |
| ITOM records are mistaken for formal DMC decisions | State that DMC decides offline and ITOM records; retain evidence references and recorder |
| Authorization and total investment are mixed | Use separate fields, categories, and metrics; never infer one from a single total |
| ITOM expands into professional approvals | Controlled references only; no generic HTTP, SQL, or database-write connector |
| Governance fields break old flows | Keep extensions nullable and preserve old project/requirement behavior |

## Implementation constraints

P0 delivers five-dimensional scoring, two project tracks, project classification, thresholds, and DMC records. P1 delivers lifecycle, investment semantics, and signers. P2 delivers governance reporting and controlled professional references.

Before coding, confirm the repository's `feature-local` route and create an acceptance matrix. Implementation, tests, authoritative Chinese documents, and the English mirror must ship together. This ADR and mapping are design artifacts only: they do not start the local application, change the database, synchronize GitHub, or touch IDC.

## References

- [DMC and digital project initiation policy alignment mapping](../superpowers/specs/2026-09-01-dmc-itom-governance-mapping.md)
- [ADR-0001](0001-platform-product-operations-overlay.md)
- [Platform Product Operations Hub specification](../superpowers/specs/2026-08-31-platform-product-operations-hub-design.md)
- [Product requirements](../03-PRD.md)
- [Data model](../04-数据模型设计.md)
- [API contract and architecture](../05-API契约与架构设计.md)
- [Identity and organization model](../06-用户身份与组织模型设计.md)
