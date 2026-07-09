# New_AOM — 轻量 IT 团队运营管理平台

基于 SN-AOM 简化重构：6 域（总览 / ITSM / 项目 / 需求 / 流程引擎 / 团队管理），
核心原则：创建表单必填 ≤5、派生数据零录入、事件驱动（积分 + 通知同一出口）。

## 文档

设计文档见 [docs/](docs/)：01 改造建议 → 02 字段裁剪 → 03 PRD（基准）→ 04 数据模型 → 05 API 契约与架构。

## 本地启动

```bash
cd deploy && docker compose up --build
# 前端 http://localhost:8080  后端 API http://localhost:8080/api/docs
# 初始管理员：admin / 见 deploy/.env 的 ADMIN_INIT_PASSWORD
```

## 开发

```bash
# 后端
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 6800
# 前端
cd frontend && npm i && npm run dev   # http://localhost:5180，/api 代理到 6800
```

## 里程碑

M1 骨架（当前）→ M2 工单+SLA+目录 → M3 ITSM 余下 → M4 项目 → M5 需求 → M6 团队+总览。
每里程碑打 git tag，验收基准为 docs/03-PRD.md 对应章节。
