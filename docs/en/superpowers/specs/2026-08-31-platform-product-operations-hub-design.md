# Platform Product Operations Hub Design (Option B)

> Status: **P0 is a locally verified candidate; P1/P2 are not implemented**
>
> Approval date: 2026-08-31
>
> Authority: the [Chinese specification](../../../superpowers/specs/2026-08-31-platform-product-operations-hub-design.md) is authoritative; this file is its English mirror.
>
> Architecture decision: [`ADR-0001: Build the Platform Product Operations Hub with optional extension profiles and a controlled observation ledger`](../../adr/0001-platform-product-operations-overlay.md)

## 1. Background and goals

After the digital-team transformation, some people work close to business domains as FDSEs while the Platform Product and Enablement team centralizes platform portfolio, demand coordination, capacity commitments, enablement assets, and operational analysis. Process design, data, AI, integration, and architecture governance remain in their dedicated professional systems; ITOM does not replace them.

This design positions ITOM as the **operations-management console for the Platform Product and Enablement team**. It will:

1. reuse the existing service catalog, requirements, projects, ITSM, investment, and reporting capabilities instead of creating duplicate master data;
2. manage platform services, demand, capacity, commitments, investment, adoption, reliability, and management decisions;
3. consume only management summaries, commitments, evidence, and synchronization state from professional systems through controlled references and metric observations;
4. let managers drill from a platform service into demand, investment, commitments, adoption, and reliability facts; and
5. preserve the existing Aily, MCP, Web Agent, domain-service, RBAC, audit, and idempotency boundaries.

## 2. Product position and boundaries

### 2.1 Position

ITOM is the operations-management console for the Platform Product and Enablement team. It manages platform services, demand, capacity, commitments, investment, adoption, reliability, and management decisions. Professional process, data, AI, integration, and architecture systems remain the systems of record for professional execution facts; ITOM collects only their management summaries, commitments, evidence, and synchronization state.

### 2.2 System-of-record boundaries

| Information | Authoritative system | ITOM responsibility |
|---|---|---|
| Service catalog, requirements, projects, tickets, unified investment | ITOM | Persist domain facts and enforce ITOM business rules |
| Process taxonomy, design, and execution detail | Professional process system | Store external references, status summaries, and management observations |
| Data, AI, integration, and architecture governance detail | Relevant professional system | Store external references, commitments, evidence, sync state, and metric observations |
| Platform capacity plans and commitments | ITOM | Version plans, approval, capacity consumption, and exception audit |
| Management reports | ITOM | Generate, review, publish, and lock by formula version and data quality |

### 2.3 Non-goals

- Reimplementing APQC, data governance, model governance, integration delivery, or architecture design in ITOM;
- providing generic HTTP, SQL, shell, or arbitrary database-write capabilities;
- copying professional records in bulk and presenting them as ITOM business master records;
- expanding the platform-service portfolio into complete project-portfolio governance, stage gates, enterprise capability maps, or roadmap execution; or
- adding Aily/MCP/Web Agent tools or allowing an agent to write tables in this phase.

## 3. Roles and responsibilities

| Role | Primary responsibility | Key restriction |
|---|---|---|
| FDSE | Register demand, add business outcomes, and read service/commitment progress within authorized domains | Cannot approve capacity or read unauthorized domains or sensitive cross-person detail |
| Professional platform team | Update its commitments, delivery evidence, and professional-system references | Cannot alter an approved capacity baseline or replace platform-product decisions |
| Platform product manager | Maintain service profiles, demand pool, objectives, enablement assets, and priority proposals | Cannot approve over-capacity commitments alone |
| Platform lead | Review the service portfolio and approve normal capacity plans and commitments | Over-capacity commitment requires a CIO exception |
| CIO/digital leader | Approve over-capacity exceptions, formal reports, and major portfolio decisions | Must provide a reason, approval record, and audit evidence |
| System administrator | Configure permissions, external systems, sync policy, and technical runtime settings | Administrator status is not a substitute for business approval |

Responsibility reuses the existing user, role, group, department, and data-scope model. No second identity or organization model is introduced.

## 4. Reusable baseline and gaps

### 4.1 Reusable capabilities

- `ServiceItem` already represents service offerings and can be the base platform-service record;
- `Requirement` already represents demand and can receive platform semantics through an optional profile;
- Projects, WBS, ITSM tickets, and generic record relations can support delivery and operations drill-down;
- the unified investment ledger already supports budget, cost, worklogs, allocation, `demand/build/run`, and `run/grow/transform`;
- the Unified Report Center already supports metric queries, templates, formal versions, audiences, drill-down, and Excel export; and
- existing permission, audit, workflow, example-read-only, and data-scope mechanisms remain reusable.

### 4.2 Main gaps

1. Service items lack platform-product owner, value proposition, lifecycle, and management scope.
2. Requirements lack target platform service, business domain, expected outcome, capacity class, and target quarter.
3. There is no quarterly capacity plan, formal commitment, immutable version baseline, or over-capacity control.
4. There is no standard representation for enablement assets, service objectives, or management summaries of professional records.
5. The Report Center lacks platform portfolio, capacity, adoption, enablement, and reliability metrics.
6. External sources lack sync-run, freshness, formula-version, conflict, and quality audit.

## 5. Product scope and user stories

### 5.1 Platform services

- A platform product manager can enable a platform profile on an existing service item without duplicating it.
- A manager can view owner coverage, lifecycle, objectives, demand, investment, commitments, and operating performance.
- A service owner can maintain management attributes without bypassing service-catalog permissions.

### 5.2 Platform demand pool

- An FDSE can link authorized-domain demand to a target platform service and describe the expected outcome.
- A platform product manager can coordinate demand by service, domain, demand class, quarter, and capacity class.
- The existing requirement workflow remains the only requirement lifecycle.

### 5.3 Capacity and commitments

- A platform lead can create quarterly capacity plans that deduct planned unavailability, BAU reserve, and risk buffer.
- A platform product manager can turn demand, roadmap, reliability, and enablement work into capacity commitments.
- A CIO can approve an over-capacity exception only with a reason and audit trail.
- An approved plan is immutable; changes create a new version.

### 5.4 Enablement and analysis

- A platform team can register templates, scripts, guides, sandboxes, training, and self-service assets.
- A manager can analyze platform portfolio, demand, capacity, investment, adoption, enablement, and reliability in the existing Report Center.
- An auditor can drill from a report metric to an internal record or external source, sync run, and observation evidence.

## 6. Architecture and integration

```text
Service Catalog ─┐
Requirements ────┼─> Platform Operations Domain ─> Unified Report Center
Projects/WBS ────┤          │                         (platform domain/templates)
ITSM ────────────┤          ├─ profiles, capacity plans, commitments, assets
Investment ──────┘          └─ external references, sync runs, observations
                                      ▲
Process/Data/AI/Integration/Architecture systems ─ controlled read-only intake ─┘
```

### 6.1 Integration principles

1. Each professional system remains the system of record for its professional facts.
2. First-phase integration is read-only by default; each connector requires system-specific approval.
3. External records use stable source identifiers and links and never masquerade as ITOM master records.
4. Every sync records its watermark, counts, outcome, error, and execution times.
5. Every observation records source time, received time, formula version, quality, and provenance.
6. The UI never provides a generic connector for arbitrary URLs, SQL, headers, or database statements.

### 6.2 Aily/MCP/Web Agent boundary

ITOM domain services and APIs remain the only write boundary for ITOM data. MCP tools cannot write the database directly or bypass business validation, workflow, RBAC, audit, or idempotency. This design adds no agent capabilities. A future capability requires a separately approved phase with code registration, user authorization, and risk classification.

## 7. Domain and data design

All new models are additive. Existing records are unaffected. A platform profile is explicitly enabled; bulk backfill must not invent business meaning.

| Target model | Relationship and purpose | Key fields (summary) |
|---|---|---|
| `platform_service_profile` | Optional 1:1 platform-product profile for `service_item` | `service_item_id`, `owner_id`, `lifecycle`, `value_proposition`, `management_scope`, audit fields |
| `platform_demand_profile` | Optional 1:1 platform-demand profile for `requirement` | `requirement_id`, `service_item_id`, `business_domain_id`, `demand_class`, `expected_outcome`, `target_quarter`, `capacity_class` |
| `platform_capacity_plan` | Versioned quarterly capacity plan by service/team | `period`, `version`, `status`, `gross_days`, reserve/buffer, `net_days`, approval fields |
| `platform_capacity_commitment` | Formal plan commitment to a specific work item | `plan_id`, subject type/ID, `commitment_type`, `capacity_days`, classifications, owner, status |
| `platform_enablement_asset` | Enablement asset catalog | type, name, service, owner, version, status, audience, external reference |
| `platform_service_objective` | Adoption, availability, self-service, or delivery objective | service, period, metric key, target, unit, formula version, status |
| `external_system` | External-source registry | source code, type, owner, sync mode, freshness threshold, status; never plaintext secrets |
| `external_work_reference` | Link an ITOM entity to an external work/design/pipeline record | internal subject, external system, external ID/URL, record type, sync summary |
| `external_sync_run` | Sync-run audit | external system, start/end, watermark, read/success/failure counts, result, error summary |
| `platform_metric_observation` | Periodic external adoption, usage, and SLO observation | metric key, service, period, value, unit, source/received time, formula version, quality, source/sync run |

### 7.1 Compatibility

- Do not rename or duplicate `ServiceItem` or `Requirement`.
- Existing service items and requirements without a profile keep their current behavior.
- The unified investment ledger remains the only internal budget, cost, worklog, and allocation ledger.
- Generic record relations remain for internal ITOM records; external references use a separate model.
- A formal report stores the observation IDs it used. Later corrections create a new version and never rewrite history.

## 8. States, workflows, and rules

### 8.1 Platform-service lifecycle

`candidate → pilot → active → retiring → retired`

Retirement never deletes historical demand, investment, commitments, observations, or report evidence. State skipping or reactivation requires authorization and a recorded reason.

### 8.2 Capacity plan

`draft → review → approved → superseded`

- An approved baseline is immutable; a revision creates a new version and supersedes the old one.
- Net capacity = gross capacity − planned unavailability − BAU reserve − risk buffer.
- Total committed capacity cannot exceed net capacity by default.
- Over-capacity commitment requires a CIO/digital-leader reason, approval, and audit.
- Commitment classification reuses `run/grow/transform` and `demand/build/run`.

### 8.3 External-observation quality

Quality states include at least `ok`, `stale`, `error`, `conflict`, and `no_data`. A ratio with no valid denominator is `N/A`, never `0%`. Conflicting, stale, and erroneous data cannot be presented as normal management evidence.

## 9. Target API contract

The following resources are targets for a later implementation phase and are not current product capabilities:

```text
GET/POST   /api/platform/services
GET/PATCH  /api/platform/services/{id}
GET/POST   /api/platform/demands
GET/PATCH  /api/platform/demands/{id}
GET/POST   /api/platform/capacity-plans
GET/PATCH  /api/platform/capacity-plans/{id}
POST       /api/platform/capacity-plans/{id}/submit
POST       /api/platform/capacity-plans/{id}/approve
POST       /api/platform/capacity-plans/{id}/revisions
GET/POST   /api/platform/capacity-plans/{id}/commitments
GET/POST   /api/platform/enablement-assets
GET/POST   /api/platform/service-objectives
GET/POST   /api/platform/external-systems
GET/POST   /api/platform/external-references
GET        /api/platform/external-systems/{id}/sync-runs
GET/POST   /api/platform/metric-observations
```

Existing `/api/reports/metrics`, `/query`, `/drilldown`, `/templates`, and formal-report endpoints will be extended with platform metrics, filters, and drill-down; no second reporting API is created. Every write enforces permission, data scope, state, concurrency, audit, idempotency, and example-read-only rules.

## 10. Metric catalog and data quality

| Theme | Representative metrics | Primary source |
|---|---|---|
| Service portfolio | Active services, owner coverage, SLA coverage, lifecycle distribution | Service catalog + service profile |
| Demand | Backlog, commitment rate, average/P50/P90 timeliness, domain/class distribution | Requirements + demand profile |
| Capacity | Available/committed person-days, utilization, reserve, overcommitment, gap | Capacity plans and commitments |
| Investment | Cost/effort by service, investment mix, cost per active user | Unified investment + observations |
| Adoption | Eligible/active users, adoption rate, self-service rate, usage | External observations |
| Enablement | Active assets, usage, onboarding lead time, completion rate | Enablement assets + observations |
| Reliability | SLO attainment, incidents, MTTR, error budget | ITSM + objectives + observations |

Every metric declares a key, name, business definition, formula version, unit, grain, source, filters, quality rule, sensitivity, and drill target. A source is labeled as existing internal, new internal, or external-dependent; the UI cannot imply that these have equal maturity.

## 11. Permissions, security, and audit

Planned permission modules:

- `platform_portfolio`: service profiles and demand pool;
- `platform_capacity`: capacity plans, commitments, review, and exceptions;
- `platform_enablement`: enablement assets and service objectives;
- `platform_integrations`: external systems, references, sync, and observations;
- existing `reports_platform` protects platform analysis and `reports_publish` controls formal publication.

Permissions reuse `AuthUser`, `RolePermission`, `UserGroup`, custom roles, and existing data-scope controls. An administrator may configure the system but cannot impersonate a business approver. External credentials never appear in URLs, logs, reports, prompts, fixtures, or responses; configuration APIs expose only non-sensitive state such as whether a secret is configured.

## 12. Information architecture and interaction

A planned top-level **Platform Operations** group contains:

1. Platform Services;
2. Platform Demand Pool;
3. Capacity and Commitments;
4. Enablement Assets.

External-system configuration belongs under System Management. The Report Center remains at the bottom of the sidebar and gains a platform-analysis domain, metrics, and templates; there is no duplicate top-level report entry.

Lists reuse the shared-table rules: first two columns frozen, single-line headers and cells by default, content-aware initial widths, horizontal scrolling, column settings, pagination, and accessible icon actions. New platform panels on existing detail pages are independent add-on sections at the bottom of the original business content.

## 13. Migration and compatibility

1. Release additive tables and optional foreign keys without changing existing business semantics.
2. Do not automatically mark every service item as a platform service or infer demand classifications.
3. Let platform product managers enable and verify profiles in controlled batches.
4. Register sources and references before approving individual connectors.
5. Show source and quality before enabling observations in formal reports.
6. Every migration provides rollback and compatible reads; existing Aily/MCP, ITSM, project, requirement, and reporting workflows must not regress.

## 14. Decision and alternatives

Adopt Option B/T2: **optional extension profiles plus a controlled observation ledger**.

| Option | Outcome | Reason |
|---|---|---|
| T1: add many fields directly to service items and requirements | Rejected | High coupling and migration risk; every record would inherit platform semantics |
| T2: optional extension profiles + controlled observation ledger | Accepted | Reuses existing domains and supports additive, auditable, phased delivery |
| T3: build a complete separate platform-management subsystem | Rejected | Duplicates service, demand, investment, and reporting capabilities at high cost |

ADR-0001 records the consequences and risks.

## 15. Phases and engineering backlog

### P0: first implementation candidate (local candidate complete)

1. P0-1 platform-service profiles and permissions;
2. P0-2 platform demand pool, classification, and service linkage;
3. P0-3 quarterly capacity plans, commitments, immutable versions, and over-capacity control;
4. P0-4 platform basics and dashboard metrics inside the existing Report Center.

### P1: management loop

1. P1-1 enablement assets;
2. P1-2 external systems and work references;
3. P1-3 observations, sync runs, and data quality;
4. P1-4 adoption, reliability, and unit-investment metrics;
5. P1-5 weekly, monthly, and quarterly platform-operation templates.

### P2: system-specific expansion

1. P2-1 separately approved professional-system connectors;
2. P2-2 separately designed and approved Web Agent read or governed capabilities.

A connector starts only after its source system, API contract, identity, data scope, and error-recovery design are known.

## 16. Acceptance and non-regression

- **P0 verified:** no duplicate Service Item or Requirement master is created; profiles retain the existing masters as their facts.
- **P0 verified:** approved capacity plans are immutable; revisions add a version and copy prior commitments.
- **P0 verified:** platform service, demand, capacity, commitments, and seven basic metrics can be queried/drilled down.
- **P0 verified:** FDSE domain, platform product manager, platform lead, CIO, and pure-administrator boundaries match the design and fail closed.
- **P0 verified:** automated coverage includes idempotent replay, changed-request conflict, capacity excess, review lock, and audit facts.
- **P1/P2 pending:** investment, adoption, reliability, external source/sync/quality, formal-report observation references, and extended `0`/`N/A` conventions.
- **Non-regression:** existing Aily/MCP/Web Agent, ITSM, project, requirement, investment, reporting, security, and audit boundaries do not change.

## 17. Documentation and implementation status

As of 2026-08-31, this option and ADR are approved and P0 has completed implementation plus focused local Docker 18180 UAT under `feature-local`. Platform Service, Demand Pool, Capacity/Commitment pages, four additive tables, P0 APIs, permission/audit/idempotency controls, and seven reporting metrics are present. P1/P2 enablement assets, external references, sync runs, observations, professional-system connectors, and agent capabilities remain unimplemented and require a new route confirmation. This status is a local candidate only; it does not claim GitHub synchronization or IDC release/acceptance.
