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

**Dashboard** shows permitted KPIs, pending work, recent activity, and project/requirement/team summaries. ITSM is split into four independent cards: service requests, changes, incidents, and problems. Each card shows that module's open/in-progress count and P1–P4 priority distribution, plus its own SLA, approval, implementation, known-error, or closure metrics; cross-module ITSM totals are no longer duplicated. Administrators can configure role landing pages. The bell shows in-app notifications; opening a notification does not replace the required action on the source record. Use **Mark all as read** to write read receipts for the current account's unread notifications, or **Clear read** to soft-delete notifications already read by that account; neither action changes the source record.

## 3. ITSM

### Service requests

The employee-facing form follows the Feishu Helpdesk pre-consultation order: User (read-only), Title, Urgency, Service Category, Specific Service Item, Problem Description, Other Supplemental Information, and Assigned Service Agent (read-only). The Assigned Service Agent field is displayed at the bottom and shows “Leave blank for back-office assignment” until a handler is assigned. Service Category is sourced from the ITSM catalog; a single matching item is selected automatically, while multiple items require an explicit selection. IT staff and administrators can expand Internal Handling Information to pre-assign an assignee or record internal remarks. The request moves through assignment, processing, acceptance, and closure. Use the current-step or “my turn” indicator to find work. Processors complete the current step; the requester closes the request after acceptance.

**End-to-end flow:** submit a published service item → assign by service item/domain → process by the current handler → requester acceptance → close and capture SLA, audit, and performance inputs. For a closed, unrated ticket, the submitter uses the 1–5-star control at the right side of the detail header; after submission the control disappears and the result remains read-only in Basic Information. A processor cannot bypass the terminal state; a failed acceptance returns the record to processing with a reason.

If more information is needed, explain it at the current step instead of changing fields to bypass the workflow. When an SLA is at risk, confirm the current handler/node before escalating or reassigning within the permission scope.

### Service catalog

Select a catalog on the left and inspect its service items on the right. Search items, filter by all/published/unpublished, sort by any header, and use the back/forward controls to return to all items. Catalogs and items have publish, unpublish, edit, and delete actions subject to permission. Deleting a catalog requires explicit confirmation and can soft-delete all child service items; historical tickets, projects, and configuration records remain intact. In the service-item editor, choose “All employees” or “Custom scope” for the audience. Custom scope opens the organization tree, where you can select departments and active employees; the server validates the references before saving and shows a readable summary in the list. The requester portal only lists items whose audience contains the current user, and ticket creation repeats the same server-side check. Administrators and IT internal roles retain the full catalog view. Templates and batch import are available for bulk maintenance. Legacy free-text audiences must be reselected in the structured editor the next time the item is edited.

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
- **System Integrations**: configure Feishu, SMTP, and AD/LDAP. Feishu includes login, organization scope, automatic sync, and frequency. Under “Feishu IT Helpdesk”, enter the Helpdesk ID, token, and event verification settings; the token is encrypted on the backend, and administrators can test access with a real ticket ID. After saving, click “Subscribe Helpdesk events”. ITOM submits the three subscriptions in Feishu's current online request format as `type` and `subtype` objects under `events`; you must also add `helpdesk.ticket.created_v1`, `helpdesk.ticket.updated_v1`, and `helpdesk.ticket_message.created_v1` in the Feishu developer console and publish the app. The configuration page exposes subscription status and field-level errors.
- **Feishu Helpdesk handoff**: after an employee submits the pre-consultation form and transfers to a human agent, ITOM creates a Pending Routing intake automatically. This administrator list is diagnostic only and cannot create the formal record. Feishu ticket details may return one `agent` or an `agents` array; ITOM recognizes both as human service and writes “Create IT service request” and “Register IT requirement” as stable links into the original conversation. The link contains no identity or token. After ITOM login, the server rechecks the signed-in account, stored intake guest, and freshly read Helpdesk guest open IDs; only a match creates a ten-minute token and opens the pre-filled form. The employee reviews title, urgency, service category, problem description, supplemental information, and service item before submission. A successful submission links the formal record and consumes the token; reopening the stable link enters that linked record. Requirement type and business domain remain explicit ITOM choices.
- **Feishu Helpdesk quick menu**: under “Settings Center → Custom Menu”, configure three entries. Use Feishu’s generated human-service link for “Transfer to human service”; use `https://public-itom-host/itsm/tickets?create=1&entry=feishu_helpdesk` for “Create service request (incident, configuration, operations)”; and `https://public-itom-host/requirements/overview?create=1&entry=feishu_helpdesk` for “Register IT requirement (new system, new feature)”. ITOM performs Feishu in-client sign-in and opens the corresponding create window. Quick-menu URLs never carry a Feishu user ID or Helpdesk token.
- **Original-conversation entry and bot fallback**: once human service is detected, the reliable outbox first sends rich links to the original Helpdesk conversation. If the tenant API rejects rich content, ITOM immediately falls back to text containing both full URLs. If Feishu returns `99991672` or says `helpdesk:all` is missing, this deterministic permission error immediately sends the same user-visible content through the application bot as a card/text instead of waiting through retries; transient errors retain retries before the card fallback. The administrator queue shows Original conversation rich content, Original conversation text, Application text fallback, or Independent bot fallback with its send time. Only the fallback card needs `/api/integrations/feishu/helpdesk/card-callback` (or unified `/events`) for `card.action.trigger`; that callback also refreshes the ticket and verifies the operator open_id. ITOM maps `customized_fields` by field key/display name and resolves service-category dropdown UUIDs through `dropdown_options`.
- **Five-point reliable sync**: after a human handoff, ITOM first creates a Pending Routing intake. The employee must choose “Create IT service request” or “Register IT requirement” in the ITOM entry card; only consuming the one-time handoff creates the formal ITOM record. If the conversation remains Pending Routing, a Helpdesk close/rating cannot create a formal record by itself. Feishu `helpdesk.ticket.created_v1`, `helpdesk.ticket.updated_v1`, and `helpdesk.ticket_message.created_v1` events are persisted by `event_id`, retried in the background, and linked to the final ITOM record by ticket ID after creation. Service requests retain the existing Intake Confirmation → Implementation & Delivery → User Confirmation & Closure flow: automatic assignment or reassignment posts Assigned (and updates the active process task), processing posts Processing, completion of the requester confirmation posts “confirmed and closing”, then the existing state machine posts Resolved and Closed. If the user confirms or closes the ticket in Feishu first, the inbound detail event advances ITOM's pending requester task or follows the reachable state-machine closure path instead of directly changing status. Feishu `status=51` means human close, `status=50` means robot close, and `solve=2` means solved. Feishu has no standalone rating event; after a ticket update/message, ITOM refreshes the ticket and accepts numeric ratings or an explicit result phrase such as “your rating: satisfied/neutral/dissatisfied” before writing `Ticket.satisfaction` and acknowledging it, without treating the rating prompt as a result. Internal notes, approval reasons, and unpublished details never leave ITOM. Administrators can open “System Management → System Integrations → Feishu IT Helpdesk” to inspect Pending Routing intakes and recent inbound events; the `/intakes` and `/sync-events` endpoints expose retry counts and errors for diagnostics.
- If Feishu reports “response data is not valid JSON” while saving an event URL, verify that the Verification Token saved in ITOM exactly matches the value on Feishu's encryption-policy page, temporarily disable Encrypt Key, and retry. ITOM compares the token as UTF-8 bytes, so the configured token does not have to be ASCII-only. Use `/api/integrations/feishu/helpdesk/events` for event verification; `/api/integrations/feishu/helpdesk/card-callback` is required only when the independent application-bot fallback is enabled.
- When local Docker is exposed to Feishu through ngrok or a reverse proxy, set `ITOM_PUBLIC_URL` in `deploy/.env` to the externally reachable HTTPS root so generated links use the correct host.
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
