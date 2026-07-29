# 设计文档 / Design Docs

中文为权威版本；`en/` 下为英文译本，供英语工程师维护开发使用。
The Chinese files are authoritative; the English translations under `en/` are for maintainers who read English.

| # | 中文 | English | 说明 / About |
|---|------|---------|------|
| 01 | [系统改造建议](01-系统改造建议.md) | [Redesign Proposal](en/01-redesign-proposal.md) | 从 SN-AOM 做减法的取舍 / How the system was slimmed down from SN-AOM |
| 02 | [字段裁剪清单](02-字段裁剪清单.md) | [Field Reduction](en/02-field-reduction.md) | 每个表单必填 ≤5 的字段裁剪 / Cutting each create form to ≤5 required fields |
| 03 | [PRD](03-PRD.md) | [PRD](en/03-PRD.md) | 产品需求（验收基准）/ Product requirements (acceptance baseline) |
| 04 | [数据模型设计](04-数据模型设计.md) | [Data Model](en/04-data-model.md) | 表结构与关系 / Tables and relationships |
| 05 | [API 契约与架构设计](05-API契约与架构设计.md) | [API & Architecture](en/05-api-and-architecture.md) | 接口约定与分层架构 / API conventions and layered architecture |
| 06 | [用户身份与组织模型设计](06-用户身份与组织模型设计.md) | [Identity & Org Model](en/06-identity-and-org-model.md) | 身份、角色、矩阵式组织、飞书 SoT / Identity, roles, matrix org, Feishu SoT |
| 07 | [岗位编制与团队岗位定义设计](07-岗位编制与团队岗位定义设计.md) | [Position & Headcount Design](en/07-position-and-headcount-design.md) | IT 团队岗位、编制和角色映射 / IT positions, headcount, and role mapping |
| 08 | [IT 团队角色绩效评分 PRD](08-IT团队角色绩效评分PRD.md) | [IT Team Role Performance PRD](en/08-it-team-role-performance-prd.md) | 矩阵角色评分、团队贡献和学习成长 / Matrix role scoring, contribution, and learning growth |
| 09 | [用户操作手册](用户操作手册.md) | [User Operation Manual](en/user-operation-manual.md) | 帮助中心式搜索、模块说明与操作步骤 / Search-first help center, module guides, and procedures |
| 10 | [Aily + MCP 正式设计基线](10-Aily-MCP版本交接与决策上下文.md) | [Aily + MCP Final Design Baseline](en/10-aily-mcp-handoff-and-decision-context.md) | 已确认基线；P0 代码/自动化/真实身份链路完成，机器人主动消息待验证 / Approved baseline; P0 code, automation, and real identity path complete; proactive bot delivery pending |

> 中文文档是产品与技术契约的权威版本，代码和测试是实现证据，三者必须保持一致；英文译本须在同一次交付中同步更新。任何影响功能、接口、数据模型、配置、部署、权限或用户流程的代码变更，如未同步受影响文档，不算完整交付。仓库总览见 [../README.md](../README.md)，执行规则见 [../AGENTS.md](../AGENTS.md)。
> Chinese docs are the authoritative product and technical contract; code and tests are implementation evidence, and all three must remain aligned. English mirrors must be updated in the same delivery. A code change affecting behavior, APIs, data models, configuration, deployment, permissions, or workflows is incomplete until the affected docs are synchronized. See [../README.md](../README.md) and [../AGENTS.md](../AGENTS.md).
