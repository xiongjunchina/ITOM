# IT Operations Platform — User Manual

> Applies to the current code version (2026-07-23).
> Audience: business users, IT team members, line owners, CIO, and system administrators.

## Using the help center

The manual is organized as a search-first help center rather than one long page:

1. After signing in, click **User Manual** immediately to the left of the language switcher.
2. Search for a module, field, action, or error message in the large search box.
3. Browse by product when you prefer a guided path: ITSM, Projects, Requirements, Team, Process, or Administration.
4. Open an article and use **On this page** to jump between how it works, procedures, and role boundaries. Use **Back to help center** to continue browsing.
5. The visible actions and scope still follow the current account's permissions. The Chinese manual is authoritative and this English page mirrors it.

## 1. Platform overview

ITOM brings IT services, projects, requirements, team capability, and workflow governance into one platform. It uses a matrix organization:

- **Business domains** are horizontal service lines with a BM, backup owner, served departments, and service team.
- **Professional lines** are vertical resource pools represented by user groups and roles.
- **Workflow-driven records** include service requests, incidents, changes, problems, requirements, and projects.
- **Digital-team scope** is the default scope for all person selectors. Administrators define this scope after Feishu or another organization source is synchronized.
- **Periodic performance** runs by quarter or annual cycle and combines role contribution, team contribution, external satisfaction, and learning-growth points.

### Sign-in and account

Use local username/password or Feishu authentication when enabled. A new Feishu identity waits for administrator approval under **System → Users & Groups → Login Provisioning**. Approval generates a 12-character initial password; an administrator may reveal or email it from the user detail page. The user should change it under **Profile → Security** after the first sign-in.

The top-right bar provides the **User Manual** button, language switcher, notifications, profile menu, and sign-out.

### Common list behavior

Business tables provide keyword search, core-field filters, clickable sortable headers, 10/20/50/100 page sizes, and a bottom horizontal scrollbar when needed. Table headers remain visible while scrolling. If a page offers a template, download the latest template and keep sheet names, column names, and hidden validation columns unchanged. Example records are read-only and may be deleted by system administrators.

## 2. Dashboard and notifications

**Dashboard** shows permitted KPIs, pending work, recent activity, and project/requirement/team summaries. ITSM is split into four independent cards: service requests, changes, incidents, and problems. Each card shows that module's open/in-progress count and P1–P4 priority distribution, plus its own SLA, approval, implementation, known-error, or closure metrics; cross-module ITSM totals are no longer duplicated. Administrators can configure role landing pages. The bell shows in-app notifications; opening a notification does not replace the required action on the source record.

## 3. ITSM

### Service requests

Create a request with title, service item, description, priority, and attachments. The request moves through assignment, processing, acceptance, and closure. Use the current-step or “my turn” indicator to find work. Processors complete the current step; the requester closes the request after acceptance.

**End-to-end flow:** submit a published service item → assign by service item/domain → process by the current handler → requester acceptance → close and capture SLA, audit, and performance inputs. A processor cannot bypass the terminal state; a failed acceptance returns the record to processing with a reason.

If more information is needed, explain it at the current step instead of changing fields to bypass the workflow. When an SLA is at risk, confirm the current handler/node before escalating or reassigning within the permission scope.

### Service catalog

Select a catalog on the left and inspect its service items on the right. Search items, filter by all/published/unpublished, sort by any header, and use the back/forward controls to return to all items. Catalogs and items have publish, unpublish, edit, and delete actions subject to permission. Templates and batch import are available for bulk maintenance.

### CMDB, SLA, incidents, changes, problems, vendors, contracts, and knowledge

CMDB maintains configuration items and relationships. SLA defines response and resolution targets and feeds service metrics. Incidents record restoration work; changes record risk, approval, implementation, and rollback; problems record root-cause analysis and permanent fixes. Vendors and contracts maintain supplier governance and renewal data. Knowledge articles are created, published, linked, and archived. These pages share search, filters, sorting, pagination, and permission-controlled editing.

**Change lifecycle:** request scope, affected services/items, window, risk, validation, and rollback → risk assessment → approval → implementation → service verification → closure. Implementation starts only after approval. Rejection requires a reason and returns to the configured correction step; a failed verification is rolled back or linked to an incident before closure.

**Incident/problem hand-off:** incidents optimize service restoration and capture impact, urgency, recovery, and review. Repeated incidents can be escalated into a problem for root-cause analysis, known error, permanent fix, and verification before the problem is closed.

## 4. Project management

Project list manages project records; project portfolios group and summarize them. Create a project with name, digital-team project manager, dates, budget, portfolio, and description. A charter Word file can populate goals, scope, organization, milestones, and a WBS draft.

WBS supports 0/50/100% presets and custom 0–100% integers. Setting a parent to 100% cascades to descendants; editing children rolls the parent up by direct-child average. Overall project progress is duration-weighted across leaf tasks. The wide WBS table freezes its header and first three columns, supports resizable columns/rows, and retains one bottom horizontal scrollbar.

**Delivery loop:** charter/launch → baseline plan (milestones, WBS, budget, risks) → execution monitoring → change decision when scope/date/budget moves → acceptance → closure retrospective. The project manager owns the baseline and closure; task owners update leaf work; PMO monitors delivery quality. A project cannot close while required child tasks remain open.

## 5. Requirement management

Business users register requirements. IT teams clarify, score, evaluate solutions, and route them to development, project delivery, deferment, or rejection. Task Tracking shows the resulting tasks, owners, dates, and completion. Scoring Rules defines dimensions, weights, and score bands. The process and its assignees/CC recipients are controlled by workflow configuration.

**Responsibility flow:** the requester defines value and acceptance; IT BP/professional owners clarify scope, dependencies, and feasibility; review/approval nodes must create an explicit approve or reject decision; an accepted requirement routes to delivery work or a project; the business owner accepts the evidence before closure. A comment alone is not an approval.

## 6. Team management

### Team overview

Shows active headcount, training, campaigns, hiring demand, workload, and points. The dashboard layout is personal to the current account.

### Performance

Performance scoring defaults to 80% role contribution plus 20% team contribution. Overview shows reference, adjusted, bonus/penalty, and final scores. Scoring Rules defines role dimensions and configurable team-contribution targets/weights. Graded Review displays one row per employee and opens a detail page for role weights, evaluator identities, evaluator weights, dimensions, reasons, and evidence. Multiple evaluators are aggregated by their configured weights.

External Raw Data accepts only `external_business_satisfaction`, and its target must be a business domain. Enter a 0–100 percentage; the configured internal/external satisfaction ratio produces the derived score. It affects the domain owner, backup owner, and IT BP for that domain. IT PMO is directly reviewed by CIO, while IT PMO can perform the initial review for IT project managers. Final Results exposes only published employee results.

### Headcount, learning, points, and culture

Headcount contains Position Definitions and Hiring Needs. Administrators and CIO can edit rows inline or in detail, delete, export, download templates, and batch import. Learning & Growth contains Training Development and Learning Tasks. Learning Tasks record a cycle goal, progress, evidence, and notes; 0–100% progress converts to team-contribution points. Activity Points maintains campaign and contribution records. Team Charter maintains vision, annual goals, and working principles.

## 7. Process center

Process Definitions configure versions, processing/approval node types, handlers, CC recipients, roles, and automation levels. New records use the published version; existing records retain their creation snapshot. Process Monitor filters running records by type, state, current node, owner, and time. Approval nodes support Approve or Reject; rejection requires a reason, while approval comments are optional. Processing nodes use Complete Step. CC recipients receive notifications without a task.

## 8. System administration

- **Organization**: maintain the department tree and people master data; choose the digital-team department scope; create business domains from organization departments and optionally include descendants.
- **Users & Groups**: manage accounts, linked people, roles, groups, status, provisioning, and initial passwords. Groups represent professional resource pools and can grant roles.
- **Roles & Permissions**: maintain built-in/custom roles, provisioning rules, and module actions (view/create/edit/delete). Admin is implicitly all-powerful; auditor is read-only.
- **Data Dictionary / State Machine**: maintain reusable values, states, colors, and allowed transitions.
- **System Integrations**: configure Feishu, SMTP, and AD/LDAP. Feishu includes login, organization scope, automatic sync, and frequency.
- **Interface & Branding**: configure names, descriptions, logos, favicon, theme, density, sidebar, landing pages, announcements, and environment markers. Images are cropped before saving.
- **Audit Log**: search changes by entity, action, actor, and time.

## 9. Profile center

Profile provides basic information, security, notification preferences, activity records, Feishu binding, theme, and content density. Password changes clear the administrator-held initial-password ciphertext. Activity records are limited to the current user.

## 10. Troubleshooting

- Missing menu or people: check role/module permission and digital-team scope, then sign in again.
- Disabled workflow action: check current assignee, claim state, terminal state, and active process version.
- Import failure: download a fresh template, preserve sheet/column names, and fix the returned sheet/row errors.
- Unchanged performance: recompute the period, verify domain-based external input and saved learning tasks, and confirm publication state.
- When reporting an issue, include path, role, steps, time, error text, record/period, and screenshot. Never send passwords, tokens, or SMTP secrets.
