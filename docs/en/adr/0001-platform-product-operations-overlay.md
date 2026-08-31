# ADR-0001: Build the Platform Product Operations Hub with optional extension profiles and a controlled observation ledger

- Status: Accepted
- Date: 2026-08-31
- Decision owner: ITOM product owner
- Scope: operations-management capabilities for the Platform Product and Enablement team
- Authority: the [Chinese ADR](../../adr/0001-platform-product-operations-overlay.md) is authoritative; this file is its English mirror.

## Context

ITOM must support collaboration between FDSEs and platform teams, but it is an operations-management tool for the Platform Product and Enablement team rather than the professional execution system for process, data, AI, integration, and architecture teams. The current product already has a service catalog, requirements, projects, ITSM, unified investment, reporting, permission, audit, and domain-service boundaries. Duplicating those domains would create dual master data and duplicate workflows.

Platform operations also needs platform-product ownership, lifecycle, demand attribution, capacity plans, formal commitments, enablement assets, professional-record references, metric observations, and data-quality semantics. An architecture decision is required to balance reuse of ITOM with the authority of professional systems.

## Decision

Adopt **optional extension profiles plus a controlled observation ledger**:

1. `ServiceItem` and `Requirement` remain the only service and demand master records.
2. Optional 1:1 profiles add platform-service and platform-demand semantics; records without profiles keep their current behavior.
3. ITOM adds versioned capacity plans, capacity commitments, enablement assets, and service objectives.
4. Professional process, data, AI, integration, and architecture systems remain the systems of record for their professional facts.
5. ITOM stores only external-system registration, stable external references, sync runs, and metric observations with provenance, formula version, and quality.
6. External intake is read-only by default in the first phase. There is no generic arbitrary HTTP, SQL, shell, or database-write connector.
7. Platform analysis extends the existing Unified Report Center; it does not create a second report center.
8. The unified investment ledger remains the only internal budget, cost, worklog, and allocation ledger.
9. Existing identity, organization, RBAC, data scope, audit, workflow, idempotency, example-read-only, and domain-service boundaries continue to apply.
10. This decision adds no Aily, MCP, or Web Agent tool. A future intelligent capability requires separate design and approval and must use a code-registered domain-service capability.

Every new table and endpoint is additive. The system must not automatically mark all service items or requirements as platform records or use bulk backfill to invent business meaning.

## Alternatives

### T1: Add all platform fields directly to service items and requirements

Rejected. The implementation path is shorter, but every service item and requirement would inherit platform-product semantics, increasing nullable fields, migration risk, permission coupling, and release coupling while making controlled adoption difficult.

### T2: Optional extension profiles and a controlled observation ledger

Accepted. Existing domain master records are reused while new semantics are isolated in additive models. Professional facts remain in their source systems, and ITOM creates an auditable management view suitable for phased P0–P2 delivery.

### T3: Build a complete separate platform-management subsystem

Rejected. It would duplicate service, demand, project, investment, reporting, identity, and permission capabilities and create dual master data, cross-domain synchronization, and excessive maintenance cost outside ITOM's management-tool position.

## Consequences

### Positive consequences

- Maximum reuse of the existing service catalog, requirement, investment, and reporting investments.
- No behavior change for records that are not part of platform operations, keeping migration controlled.
- Clear internal/external fact boundaries and metrics traceable to sources and sync runs.
- A management loop across services, demand, capacity, investment, adoption, and reliability.
- Future connectors can be evaluated and authorized one system at a time.

### Costs and constraints

- Queries and reports aggregate across base records, profiles, investments, and observations.
- Platform product managers must explicitly enable and govern profiles rather than rely on unreviewed backfill.
- External metrics require freshness, conflict, error, no-data, and formula-version handling.
- Capacity planning adds version, approval, concurrency, and over-capacity exception controls.
- Every connector requires its own contract, security, and operating design.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| ITOM expands into a professional execution system | Enforce the system-of-record matrix and non-goals; connectors collect only management summaries and evidence |
| Dual master data or semantic drift | Reuse `ServiceItem`, `Requirement`, and unified investment; profiles contain additional semantics only |
| External data is mistaken for live and correct data | Expose source time, received time, quality, and freshness; show `stale/error/conflict/no_data` explicitly |
| Uncontrolled over-capacity commitments | Reject commitments above net capacity by default; require a CIO reason, approval, and audit for exceptions |
| Permission overreach | Reuse functional, sensitive, and data-scope permissions; administrator status does not replace business approval |
| Agent bypasses domain rules | Add no generic tool; any future capability must call domain services and receive separate approval |

## Implementation constraints

The first implementation candidate covers only P0-1 through P0-4: platform-service profiles, the platform demand pool, quarterly capacity and commitments, and basic platform analysis in the existing Report Center. External connectors, external metric observations, and Web Agent capabilities are outside P0.

Implementation has not started when this ADR is accepted. Before development, the repository's task route must be confirmed separately and an acceptance matrix must keep code, tests, authoritative Chinese documentation, and the English mirror consistent.

## References

- [Platform Product Operations Hub specification](../superpowers/specs/2026-08-31-platform-product-operations-hub-design.md)
- [Product requirements](../03-PRD.md)
- [Data model](../04-data-model.md)
- [API contract and architecture](../05-api-and-architecture.md)
- [Identity and organization model](../06-identity-and-org-model.md)
- [Aily + MCP handoff and decision context](../10-aily-mcp-handoff-and-decision-context.md)
