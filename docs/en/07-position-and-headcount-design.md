# Position & Headcount Design

> Status: design baseline (2026-07-22)
> Scope: Team Management → Position & Headcount → Position Definitions
> Goal: provide an executable staffing baseline for growing the IT team from about 30 people to 60 formal employees, with an additional 10–20 contractors.

## 1. Design principles

1. **Separate positions from roles**: a position describes responsibilities, capabilities, and headcount; a built-in role describes system permissions. A position may recommend one or more roles, but it must not grant permissions automatically.
2. **Matrix organization**: business-facing service lines cover market/sales, supply chain/production, product/R&D, and finance/corporate services; professional lines cover product, development, and operations.
3. **Cross-domain platform capabilities**: PMO, data governance, AI, information security, architecture, and the service desk are cross-domain capabilities.
4. **Headcount means formal employees**: `headcount` counts formal employees only. Contractors are governed through contracts, delivery scope, and service quality.
5. **Start with a runnable minimum**: the first version focuses on responsibilities and headcount; level, skills, locations, current staffing, and contractor attributes can follow.

## 2. Built-in roles and position boundaries

The current role set includes `admin`, `cio`, `it_bm`, `it_tm`, `it_pdm`, `it_pdm_leader`, `it_pm`, `it_pmo`, `it_dev`, `it_dev_leader`, `it_ops`, `it_op_leader`, `is_mgr`, `it_bp`, `auditor`, and `requester`.

`admin` is a restricted system-administration responsibility, not a staffing position. `auditor` and `requester` are user-facing access roles, not IT positions. A person may hold multiple roles; for example, a development lead may hold both `it_dev_leader` and `it_tm`.

## 3. Position definition list

The following `headcount` values are the target formal-employee headcount and total 60.

### 3.1 Governance and business service lines: 17

| Position | HC | Primary role | Responsibility boundary |
|---|---:|---|---|
| CIO / Head of IT | 1 | `cio` | IT strategy, budget, organization, major programs, major risks, and governance outcomes. |
| IT Business-line Lead—Market & Sales | 1 | `it_bm` | Service portfolio, prioritization, resources, and satisfaction for GCBG/CCBG. |
| IT Business-line Lead—Supply Chain & Production | 1 | `it_bm` | Digital services and system coordination for SCBG, Foshan, Indonesia, and Oman factories. |
| IT Business-line Lead—Product & R&D | 1 | `it_bm` | IT services for PBG product, R&D, quality, and engineering efficiency. |
| IT Business-line Lead—Finance & Corporate Services | 1 | `it_bm` | FSD, collaboration, and company-wide management services. |
| IT Product Lead | 1 | `it_pdm_leader` | Product management system, intake, roadmap, solution evaluation, and product team. |
| IT Discipline Lead—Product | 1 | `it_tm` | Product-manager pool, methods, capability development, and quality. |
| IT Discipline Lead—Development | 1 | `it_tm` | Development pool, technical capability, delivery quality, and engineering efficiency. |
| IT Discipline Lead—Operations | 1 | `it_tm` | Operations pool, service desk, infrastructure, incident, and change management. |
| IT PMO / Project Governance | 2 | `it_pmo` | Portfolio, initiation, milestones, risks, budget, retrospectives, and management reporting. |
| IT Project Manager | 2 | `it_pm` | Cross-functional plans, resources, risks, testing, go-live, and acceptance. |
| IT Business Partner—Market & Sales | 1 | `it_bp` | Business alignment, demand clarification, and follow-up for market and sales. |
| IT Business Partner—Supply Chain & Production | 1 | `it_bp` | Demand alignment for ERP, MES/WMS, and factory digitization. |
| IT Business Partner—Product & R&D | 1 | `it_bp` | Demand alignment for product, R&D, quality, and collaboration. |
| IT Business Partner—Finance & Corporate Services | 1 | `it_bp` | Demand alignment for finance, collaboration, HR/OED, and company-wide services. |

### 3.2 Product and architecture: 12

| Position | HC | Primary role | Responsibility boundary |
|---|---:|---|---|
| IT Product Manager—Market & Sales | 2 | `it_pdm` | E-commerce, Amazon VC, channels, marketing, customer service, and sales analytics. |
| IT Product Manager—Supply Chain & Production | 3 | `it_pdm` | Polaris ERP, MES/WMS, planning, warehousing, quality, and factory systems. |
| IT Product Manager—Product & R&D | 2 | `it_pdm` | Product lifecycle, BOM, R&D collaboration, testing, and quality systems. |
| IT Product Manager—Finance & Collaboration | 1 | `it_pdm` | Kingdee, Feishu, Seeyon migration, expenses, and workplace collaboration. |
| IT Product Manager—Data & AI | 2 | `it_pdm` | Data products, management analytics, AI applications, and intelligent scenarios. |
| Enterprise Architect | 1 | `it_pdm_leader` / `it_dev_leader` | Enterprise architecture, system boundaries, standards, integration, and retirement roadmap. |
| Solution Architect | 1 | `it_pdm_leader` / `it_dev_leader` | Complex solutions, technology selection, integration design, and feasibility. |

### 3.3 Development, data, and intelligence: 17

| Position | HC | Primary role | Responsibility boundary |
|---|---:|---|---|
| IT Development Lead | 1 | `it_dev_leader` | Development planning, technical review, code quality, delivery scheduling, and resource allocation. |
| Business Application Developer | 5 | `it_dev` | ERP, MES/WMS, finance, collaboration, and market application development and maintenance. |
| Integration & Platform Developer | 3 | `it_dev` | APIs, messaging, SSO, workflows, data exchange, and application platform. |
| Data Engineer & Data Governance Specialist | 4 | `it_dev` | Data platform, master data, standards, quality, metrics, and data services. |
| AI & Intelligent Applications Engineer | 2 | `it_dev` | AI platform, knowledge assistants, forecasting, RPA, and model applications. |
| QA & Release Engineer | 2 | `it_dev` / `it_ops` | Test strategy, automation, release process, go-live verification, and quality gates. |

### 3.4 Operations, infrastructure, and security: 14

| Position | HC | Primary role | Responsibility boundary |
|---|---:|---|---|
| IT Operations Lead | 1 | `it_op_leader` | Service desk, incidents, problems, changes, SLA, infrastructure, and operations team. |
| Service Desk & Application Operations Engineer | 3 | `it_ops` | Unified intake, incident handling, application support, knowledge, and user experience. |
| Cloud, Systems & Database Engineer | 3 | `it_ops` | Cloud, servers, operating systems, databases, middleware, storage, and backup. |
| Network & Site IT Engineer | 3 | `it_ops` | Headquarters, Foshan, Indonesia, Oman networks, VPN, SD-WAN, and site support. |
| SRE / Monitoring / Backup Engineer | 1 | `it_ops` | Observability, capacity, alerting, backup/recovery, and reliability improvement. |
| Information Security Lead | 1 | `is_mgr` | Security policy, risk assessment, major incidents, audit, and compliance. |
| Information Security Engineer | 2 | `is_mgr` | Endpoint, identity, vulnerability, patch, data security, and security operations. |

## 4. Headcount and contractor boundary

The target formal headcount is 60. Current staff of about 30 can be mapped to these positions over time; the position gap is calculated as `headcount - active_count`.

The 10–20 contractors should mainly cover legacy maintenance, special development, testing, data cleansing/ETL/migration, factory site support, L1 service desk, network/device implementation, and short-term delivery. They should not own enterprise architecture, master data, security decisions, change approval, product roadmaps, demand prioritization, or final system ownership.

## 5. Data-model handoff for the coding agent

The current minimum position definition is:

| Field | Recommendation |
|---|---|
| `name` | Required position name; unique among non-deleted rows. |
| `duties` | Responsibility boundary; initially may include service domain, role recommendation, and contractor boundary. |
| `headcount` | Non-negative integer formal-employee target headcount. |

The implementation adds `position_code`, `position_family`, `service_domains`, `primary_roles`, `level_framework`, `location_scope`, `skills`, `contractor_allowed`, `status`, and `sort`. `active_count` remains computed from personnel assignments, and `gap` remains `headcount - active_count` rather than a hand-maintained field.

Position definitions and hiring needs should be one-to-many: one position can have multiple hiring needs by level, batch, or hiring status. A hiring need separately stores level, count, qualification, status, and progress.

## 6. Ongoing governance guidance

1. Keep `org_member.position_id` linked to the position definition; Feishu synchronization must not overwrite locally managed position, skills, or remarks.
2. Continue granting permissions through users, groups, and the permission matrix; do not write `auth_user.roles` directly from position records.
3. Express data governance, AI, service desk, and other cross-domain capabilities through user groups/resource pools, while position definitions express individual accountability.

## 7. Implementation status (2026-07-22)

The recommendations above are now implemented in Team Management → Position & Headcount:

- Position definitions include position code, family, service domains, primary roles, level framework, location scope, key skills, contractor boundary, status, sort order, responsibilities, and formal headcount.
- Formal onboard and gap are computed in real time from active IT-team members. Formal employees are counted; contractors and interns are excluded (legacy records with no employment type remain compatible).
- The position list supports server-side pagination and name/code search. `org_member.position_id` remains locally managed and is not overwritten by Feishu organization synchronization.
- Position definitions support Excel export, template download, and batch import. Imports match by position code first and name second, support create/update, and return row-level failure reasons.
- Hiring needs remain one-to-many with positions and support Excel export, template download, and batch import. Existing exported need IDs update records; otherwise a new need is created by position code/name.
- System administrators and CIOs have default edit/delete permissions for both lists. Each list supports inline row editing with save/cancel and delete; referenced positions are protected until their people and hiring needs are handled.
- Excel imports accept `.xlsx` files up to 5 MB, preserve valid rows on partial failure, and write an audit record. Recoverable invalid column widths (written by some online spreadsheet exporters as oversized column numbers) are cleaned automatically; other corrupt/non-standard workbooks, over-length fields, position code/name conflicts, and codes belonging to deleted positions are reported as row-level import errors instead of surfacing as an HTTP 500.

API contract: `GET /api/positions/template`, `GET /api/positions/export`, `POST /api/positions/import`; hiring needs use `/api/hiring-needs/template`, `/api/hiring-needs/export`, and `/api/hiring-needs/import`.
