# IT-Staff Intake and Cross-Record Relationship Design Baseline

> Status: **phases A/B/C implemented; phase D pending**
> Approval date: 2026-07-31
> The Chinese document is authoritative; this is its English mirror.

## 1. Purpose

ITOM manages service requests, incidents, problems, changes, IT requirements, and projects. Normal employees will primarily use Feishu Aily and must not have to choose an ITIL record type. IT staff need a lightweight, explainable web intake path to reduce incorrect records and to link or transfer work with a complete audit trail.

This design covers only IT-staff web routing, compact explanations, recommendations, and cross-record relationships. It does not change Aily's normal-user entry, MCP scope, existing record types, historical data, or existing workflow instances.

## 2. Confirmed boundaries

| User | Entry | Creation scope | Effect of this design |
| --- | --- | --- | --- |
| Normal employee | Feishu Aily | Service request and IT requirement | **Unchanged**. Aily does not create incidents, problems, changes, or projects and does not perform transfers. |
| IT staff and system administrators | Global ITOM “Record Creation Guide” action | Determined by actual create permission | Adds a lightweight guide, recommendation, and target navigation. |
| Admin/CIO | ITOM web | Determined by the permission matrix | Manages permissions, audit, and later metrics. |

The unified entry is visible only in the IT-staff web experience. It neither adds a normal-user Web entry nor changes Aily request creation, requirement registration, query, confirmation, reopen, or rating.

The underlying definitions remain unchanged: a service request is an individual's request for help with an existing capability; an incident is broad network/server/application impact or monitoring-detected interruption; a problem is a known error/recurrent issue requiring root cause work; a change is a planned, controlled production modification; an IT requirement is a new system/function/optimization/refactor idea requiring evaluation; and a project is structured delivery requiring charter/WBS/milestones/resources/cost/risk, normally at or above the project effort threshold.

## 3. Lightweight routing for IT staff

### 3.1 Entry and guide

The global action is named “Record Creation Guide” and opens a drawer/modal. It asks two to four **temporary** questions and recommends a record type; the user may override it and always enters the existing target creation form.

Initial rule order:

1. Multi-user, service-wide, or critical-system impact → incident.
2. Recurrence, known error, or root-cause investigation → problem.
3. Planned production modification with risk, rollback, or window → change.
4. New system/function/optimization/refactor idea → IT requirement.
5. Other individual help, failure, or request for an existing capability → service request.

The guide returns a recommendation, rationale, counterexample, and accessible target entry. It stores no answers, creates no new business fields, and never replaces target-form permissions, mandatory fields, or workflow validation.

### 3.2 Compact explanation and case library

Each of the six record pages shows one compact “when to use + one positive example” line beside the title, with “View examples” for details. The expanded case library contains definition, use/non-use cases, examples, and common corrections. It is the shared source for UI explanations and routing rules, initially implemented as versioned static/rule configuration rather than LLM classification.

## 4. Transfer and relation: create a target record; never mutate the source type

Principles:

1. Never rewrite a source record type, delete it, force-close it, or overwrite it.
2. Create the target through its own domain service and required fields/workflow; write the relation only after target creation succeeds.
3. Show the relation bidirectionally with counterpart code, type, creator, time, reason, and navigation; write immutable audit.
4. Source and target retain independent status, SLA, workflow, permission, and closure rules.
5. Target creation, relation write, and audit share a transaction boundary; retries are idempotent.

Initial relation whitelist:

| Source | Target | `relation_type` | Meaning |
| --- | --- | --- | --- |
| Service request | Incident | `upgraded_to_incident` | Broad impact receives incident handling |
| Service request / incident | Problem | `root_cause_of` | Root-cause or known-error management |
| Incident / problem | Change | `remediated_by_change` | Remediation requires controlled change |
| IT requirement | Project | `converted_to_project` | Evaluated requirement becomes project delivery |

Only safe context is prefilled; every target's required fields remain mandatory. Existing `problem_ticket` remains the dedicated legacy problem-ticket link and must neither be deleted nor overwritten. The implementation must prevent duplicate display for the same business relationship.

## 5. Generic `record_relation` model (Approach A)

The new model contains `id`, source/target entity type and ID, controlled `relation_type`, mandatory `reason`, created-by/time, `idempotency_key`, `request_digest`, and reserved soft-delete audit fields. It uses polymorphic entity references, so each domain service validates types and identifiers in its transaction rather than relying on cross-table polymorphic foreign keys.

An active-relation uniqueness constraint covers `(source_entity_type, source_entity_id, target_entity_type, target_entity_id, relation_type)`. The same creator/source/target-type/idempotency-key tuple is also unique and the digest rejects same-key/different-request retries. Combined source/target indexes support bidirectional reads. A self-link to the same record and arbitrary client-supplied type combinations are forbidden by a server-side whitelist; a service-request ticket may still relate to an incident ticket. No historical ticket/problem/requirement/project data, workflows, or audits will be migrated or rewritten.

The initiator needs both source-read and target-create permission. Target validation, approval, workflow, RBAC, audit, events, and data scope remain owned by the target domain service. Phase one offers no ordinary unlinking action; any future administrative unlink must be soft-deleted with a reason and audit.

## 6. APIs and UI boundary (phases B/C implemented)

```text
POST /api/staff-intake/recommend
GET  /api/it-document-guide
POST /api/record-relations/prepare
  # source record + relation_type; validates source view/target create and returns safe prefill/required target fields
POST /api/record-relations/submit
  # target form + relation_type + reason + idempotency_key; source-row lock and digest idempotency, then invokes the target domain service
GET  /api/records/{entity_type}/{entity_id}/relations
```

`recommend` is ephemeral. Phase B delivers the additive PostgreSQL migration, active-relation/idempotency uniqueness, immutable audit, read route, and bidirectional safe display in ticket, problem, requirement, and project details while preserving dedicated legacy links. Phase C implements `prepare/submit` plus the detail-page Create-and-link drawer: the server derives the target kind from its whitelist rather than trusting the client; while holding the PostgreSQL source-row lock it normalizes the target form and link reason with Pydantic, computes a digest, and checks the same actor/source/target-kind/idempotency key. The same request returns the first target and same-key different input is rejected; only an unmatched request invokes the incident, problem, change, or project domain service and writes target, workflow, relation, and audit in one transaction.

## 7. Delivery phases and acceptance

| Phase | Delivery | Acceptance |
| --- | --- | --- |
| A (implemented) | IT-staff entry, temporary guide, compact explanations, case library | Aily normal-user flow unchanged; no guide answers persisted; explainable/reversible recommendation; compact default header |
| B (implemented) | `record_relation`, migration, reads, bidirectional detail section, audit/permission/idempotency | Existing data and dedicated links preserved; unauthorized users cannot read relations; retries do not duplicate relations |
| C (implemented) | Four create-target-and-relate paths | Independent target workflow; source type/status unchanged; no partial record on failure; every relation has a reason |
| D | Recommendation override/hit feedback and case-library governance | Improve rules from IT-staff use without expanding Aily permissions |

Every phase requires migration/unit/API regression tests, frontend build, Chinese authoritative docs plus English mirror, IDC Kubernetes deployment, and real IDC user-flow validation. No MCP tool is added for this design; any future Aily scope expansion needs separate approval.

## 8. Non-goals

This is not AI automation of IT professional judgment, an ITIL routing burden for normal business users, a persistent classification questionnaire, a first-phase unlink/reversal feature, a complex relation graph, or automatic cross-record closure. Any future LLM recommendation requires separate confirmation of model, data boundary, human confirmation, audit, and fallback.
