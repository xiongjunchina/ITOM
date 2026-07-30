# IT Operations Platform — User Manual

> Applies to the current code version (2026-07-30, Aily-MCP P2.1).
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

**Dashboard** shows permitted KPIs, pending work, recent activity, and project/requirement/team summaries. ITSM is split into four independent cards: service requests, changes, incidents, and problems. Each card shows that module's open/in-progress count and P1–P4 priority distribution, plus its own SLA, approval, implementation, known-error, or closure metrics; cross-module ITSM totals are no longer duplicated. Administrators can configure role landing pages. The bell shows in-app notifications; opening a notification does not replace the required action on the source record. Use **Mark all as read** to write read receipts for the current account's unread notifications, or **Clear read** to soft-delete notifications already read by that account; neither action changes the source record.

## 3. ITSM

### Service requests

After the requester selects a service item, ITOM loads that item's currently published form version and renders its dynamic fields. The web form and Aily MCP share the same required, type, length, option, date, person/department scope, and conditional-rule validation. Only published, non-example items within the requester's audience are selectable. On submission, ITOM stores the form version and schema snapshot, starts the process bound to the item, and dispatches by item rule, catalog rule, then global fallback. If no eligible handler exists, the record enters a manual queue instead of being silently dropped. IT staff and administrators can still use Internal Handling Information where permitted.

**End-to-end flow:** submit a published service item → dispatch → IT acceptance/processing → pending requester confirmation → close → rate. IT completion moves only to `resolved`; only the submitter may confirm closure, and an administrator cannot confirm on the submitter's behalf. “Not resolved” returns the workflow to the nearest real handling step and increments reopen count; the next resolution shows the latest active handling note. A closed request can be rated with 1–5 stars, up to five tags, and an optional 500-character comment; the result remains in Basic Information and is audited.

If more information is needed, explain it at the current step instead of changing fields to bypass the workflow. When an SLA is at risk, confirm the current handler/node before escalating or reassigning within the permission scope.

### Service catalog

Select a catalog on the left and inspect its service items on the right. Search items, filter by all/published/unpublished, sort by any header, and use the back/forward controls to return to all items. Catalogs and items have publish, unpublish, edit, and delete actions subject to permission. Deleting a catalog requires explicit confirmation and can soft-delete all child service items; historical tickets, projects, and configuration records remain intact. In the service-item editor, maintain search keywords, synonyms, typical/excluded scenarios, the bound process, default priority, and an audience of All employees or a structured Custom scope. The requester portal and MCP search only expose published, non-example items whose audience contains the current user. Use the item's **Form / Dispatch** action to create and publish versioned forms and configure fixed-person, fixed-group, round-robin, or manual-queue dispatch. P1's visual designer supports short/long text, single/multi-select, number, date/datetime, person, department, and boolean fields. Published versions are not overwritten in place, and historical tickets retain their answer/schema snapshot. Templates and batch import remain available for bulk maintenance.

### CMDB, SLA, incidents, changes, problems, vendors, contracts, and knowledge

CMDB maintains configuration items and relationships. SLA defines response and resolution targets and feeds service metrics. Incidents record restoration work; changes record risk, approval, implementation, and rollback; problems record root-cause analysis and permanent fixes. Vendors and contracts maintain supplier governance and renewal data. Knowledge articles are created, published, linked, and archived. These pages share search, filters, sorting, pagination, and permission-controlled editing.

**Current published change flow:** `it_ops` registers the change (scope, affected services/items, window, risk, validation, and rollback) → `it_op_leader` approves it (`it_bm` is notified) → `it_ops` implements and verifies it → `is_mgr` performs the change retrospective/PIR (`cio` is notified). Implementation starts only after approval. The current state machine allows `cio`, `it_tm`, and `it_op_leader` to approve/reject; rejection requires a reason. A failed verification is rolled back or linked to an incident before closure. The published process version takes precedence over code seeds; process changes require a new version.

**Incident/problem hand-off:** incidents optimize service restoration and capture impact, urgency, recovery, and review. Repeated incidents can be escalated into a problem for root-cause analysis, known error, permanent fix, and verification before the problem is closed.

## 4. Project management

Project list manages project records; project portfolios group and summarize them. Create a project with name, digital-team project manager, dates, budget, portfolio, and description. A charter Word file can populate goals, scope, organization, milestones, and a WBS draft.

WBS supports 0/50/100% presets and custom 0–100% integers. Setting a parent to 100% cascades to descendants; editing children rolls the parent up by direct-child average. Overall project progress is duration-weighted across leaf tasks. The wide WBS table freezes its header and first three columns, supports resizable columns/rows, and retains one bottom horizontal scrollbar.

**Delivery loop:** charter/launch → baseline plan (milestones, WBS, budget, risks) → execution monitoring → change decision when scope/date/budget moves → acceptance → closure retrospective. The project manager owns the baseline and closure; task owners update leaf work; PMO monitors delivery quality. A project cannot close while required child tasks remain open.

## 5. Requirement management

Business users register requirements. IT teams clarify, score, evaluate solutions, and route them to development, project delivery, deferment, or rejection. Task Tracking shows the resulting tasks, owners, dates, and completion. Scoring Rules defines dimensions, weights, and score bands. The process and its assignees/CC recipients are controlled by workflow configuration.

At least one active business domain must be configured before registration. The web UI and Aily MCP select only from that live list and never invent a domain. When the list is empty, MCP returns an explicit submission blocker and an administrator must first configure a domain under **System Management → Organization → Business Domains**.

**Responsibility flow:** the requester defines value and acceptance; IT BP/professional owners clarify scope, dependencies, and feasibility; review/approval nodes must create an explicit approve or reject decision; an accepted requirement routes to delivery work or a project; the business owner accepts the evidence before closure. A comment alone is not an approval.

## 6. Team management

### Team overview

Shows active headcount, training, campaigns, hiring demand, workload, and points. The dashboard layout is personal to the current account.

### Performance

Performance scoring uses 80% role-result contribution plus 20% team contribution. Overview reads the current matrix-role period result and shows role contributions, team contribution, adjustments, and the current total; expanding an employee shows roles, weights, system reference, manager proposals, CIO final scores, and effective scores. It no longer displays the legacy job-scheme default. The current model has no global default scheme: use **Scoring Rules → Add role rule** to create a reusable role rule, then assign the role and weight in the employee-period detail. Scoring Rules defines role dimensions, source/RACI mappings, and weights; Activity Points → Point Rules defines team-contribution targets and event values. Graded Review remains the detailed scoring workflow, with multiple evaluators aggregated by their configured weights.

External Raw Data accepts only `external_business_satisfaction`, and its target must be a business domain. Enter a 0–100 percentage; the configured internal/external satisfaction ratio produces the derived score. It affects the domain owner, backup owner, and IT BP for that domain. IT PMO is directly reviewed by CIO, while IT PMO can perform the initial review for IT project managers. Final Results exposes only published employee results.

### Headcount, learning, points, and culture

Headcount contains Position Definitions and Hiring Needs. Administrators and CIO can edit rows inline or in detail, delete, export, download templates, and batch import. Learning & Growth contains Training Development and Learning Tasks. Learning Tasks record a cycle goal, progress, evidence, and notes; 0–100% progress converts to team-contribution points. Activity Points maintains campaign and contribution records; its sibling Point Rules tab owns team-contribution event configuration. Team Charter maintains vision, annual goals, and working principles.

## 7. Process center

Process Definitions configure versions, processing/approval node types, handlers, CC recipients, roles, and automation levels. New records use the published version; existing records retain their creation snapshot. Process Monitor filters running records by type, state, current node, owner, and time. Approval nodes support Approve or Reject; rejection requires a reason, while approval comments are optional. Processing nodes use Complete Step. CC recipients receive notifications without a task.

## 8. System administration

- **Organization**: maintain the department tree and people master data; define the digital-team scope as the union of selected department members and individually selected people; create business domains from organization departments and optionally include descendants. In a mixed Test/vendor organization, select only the contractors who participate in IT work and performance reviews—their colleagues are not included.
- **Users & Groups**: manage accounts, linked people, roles, groups, status, provisioning, and initial passwords. Linked Person uses the complete company organization, shows a readable person and department, and is not limited to the digital-team scope. Administrators can rebind or clear the person; clearing does not delete the person, department placement, group membership, or history. Groups represent professional resource pools and can grant roles.
- **Roles & Permissions**: maintain built-in/custom roles, provisioning rules, and module actions (view/create/edit/delete). Admin is implicitly all-powerful; auditor is read-only.
- **Data Dictionary / State Machine**: maintain reusable values, states, colors, and allowed transitions.
- **System Integrations**: configure Feishu, SMTP, and AD/LDAP. Feishu application credentials, sign-in, organization scope, automatic sync, and frequency serve login and organization identity only; this version no longer configures or subscribes to Feishu Helpdesk. Aily calls ITOM business capabilities through the MCP Server.
- **Public endpoint**: under **Aily Agent + MCP Server**, enter **Public base URL (domain/IP + service port)**. The current IDC URL is `https://itom.snnc.cc:30443`. Enter the real external entry point without `/mcp/` or any callback path. After saving, the page derives the MCP URL, Feishu login callback, and card callback from the same host and port. Clearing the field removes the copyable public URLs. Production HTTPS must use a publicly trusted CA certificate that matches the host and serves a complete chain.
- **Aily + MCP identity and authorization**: `/mcp/` requires a server-issued JWT. ITOM validates its signature, lifetime, tenant, Agent, and origin, then maps the Feishu user to an enabled ITOM account. Unmapped users, out-of-audience items, and missing module permissions are rejected. MCP never writes tables directly or bypasses workflow validation.
- **P1 user intake**: Aily can search the current user's eligible service items, read a published form, produce a masked preview and one-time confirmation token, and idempotently create a `service_request` only after explicit confirmation. New-system/new-feature requests use the separate IT requirement form and requirement workflow. Ordinary users cannot create incidents, changes, or problems through Aily.
- **P2 closure loop**: Aily can list every pending confirmation owned by the current user. When more than one exists, it must ask for an explicit ticket code rather than guess the latest. The user can confirm closure or reopen with a reason, then rate a closed request with stars, tags, and comment. Acceptance/resolution/reopen/closure/rating messages come from ITOM's reliable outbox and never include internal notes, root cause, or approval details. After an administrator configures bot credentials plus the callback Verification Token and Encrypt Key under System Integrations, and subscribes only to the new `card.action.trigger` callback in Feishu Open Platform, resolution/reminder notifications show close/reopen buttons and closure notifications show 1–5-star buttons; incomplete setup remains text. Clicking unresolved opens a required reason field in the same card. Ordinary conversation remains Aily + MCP, while ITOM verifies the Feishu signature and clicker identity before applying the same domain checks for button actions.
- **Environment boundary**: IDC Kubernetes is the sole runtime, integration, and acceptance environment at the current public root `https://itom.snnc.cc:30443`. Starting local ITOM, a database, Docker Compose, port 8180, or ngrok is prohibited by default. It is allowed only for administrator-approved temporary isolated troubleshooting and never counts as formal acceptance. Localhost and private-network URLs cannot be registered with Feishu. Use the generated `/mcp/` URL, including its trailing slash, as Aily's custom-MCP request URL and `/api/integrations/feishu/card-actions` for the card callback. Never put secrets in URLs, prompts, logs, or screenshots. When the public root changes, save it again and update Aily, Feishu OAuth, and card-callback configuration.
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
