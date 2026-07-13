"""全模块示例数据（M5.1）：每个可填写字段的值本身就是填写指引。

- 业务单据示例 is_example=True：列表置顶、后端只读（EXAMPLE_READONLY）
- 支撑组织数据（部门/岗位/人员/业务域）为普通可编辑记录（带【示例】前缀，
  用户后续直接改名为真实的人和组织）
- 示例之间互相关联形成完整教学链：需求挂项目、合同挂供应商、问题挂工单、
  项目 WBS 带前置依赖（甘特图依赖线可见）
- 幂等：以示例项目存在与否为哨兵
"""
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import (
    BusinessDomain,
    Ci,
    Contract,
    CostEntry,
    Department,
    KnowledgeArticle,
    Milestone,
    OrgMember,
    Portfolio,
    Position,
    Problem,
    ProblemTicket,
    Project,
    Requirement,
    RequirementTask,
    Risk,
    ServiceCatalog,
    ServiceItem,
    Ticket,
    Vendor,
    WbsTask,
)


def run_seed_examples(db: Session):
    if db.query(Project).filter(Project.is_example.is_(True)).first():
        return

    today = date.today()
    now = datetime.now()

    # ---------- 支撑组织数据（可编辑，供用户改成真实组织） ----------
    dept = db.query(Department).filter(Department.name == "【示例】信息技术部").first()
    if not dept:
        dept = Department(code="demo_it", name="【示例】信息技术部", dept_type="it", sort=99)
        db.add(dept)
        db.flush()
    position = db.query(Position).filter(Position.name == "【示例】运维工程师").first()
    if not position:
        position = Position(name="【示例】运维工程师",
                            duties="填写指引：写清楚该岗位的分工职责边界，如：负责基础设施与应用运维、工单响应、变更实施",
                            headcount=2)
        db.add(position)
        db.flush()
    person = db.query(OrgMember).filter(OrgMember.name == "【示例】王小明").first()
    if not person:
        person = OrgMember(
            name="【示例】王小明", name_en="Wang Xiaoming", employee_no="E0001",
            gender="男", employment_type="正式", work_location="上海",
            department_id=dept.id, position_id=position.id,
            hire_date=today - timedelta(days=365), email="demo@example.com", mobile="13800000000",
            skills=["Linux", "PostgreSQL"],
            remarks="填写指引：这是示例人员，请将姓名/工号/部门等改为真实信息，或接入飞书同步后自动维护。技能标签用于岗位分工与流程派单参考",
        )
        db.add(person)
        db.flush()
    domain = db.query(BusinessDomain).filter(BusinessDomain.name == "【示例】零售业务线").first()
    if not domain:
        domain = BusinessDomain(
            code="demo_retail", name="【示例】零售业务线", owner_id=person.id,
            description="填写指引：业务域=横向服务线。负责人（BM）总体负责该业务域的 IT 支持；请改为真实业务线并指定真实负责人",
            sort=99,
        )
        db.add(domain)
        db.flush()

    # ---------- 服务目录 ----------
    catalog = ServiceCatalog(
        is_example=True, code="SC-DEMO", name="【示例】基础 IT 服务", tier="gold",
        description="填写指引：目录是服务的分类（如基础设施/应用系统/办公支持），分级 gold/silver/bronze 代表服务重要性",
        sort=0,
    )
    db.add(catalog)
    db.flush()
    item = ServiceItem(
        is_example=True, item_code="SI-DEMO", name="【示例】数据库支持服务", catalog_id=catalog.id,
        service_type="日常运维", owner=person.id,
        description="填写指引：说清服务内容与边界，如：PostgreSQL/MySQL 的安装、调优、备份恢复与故障处置",
        sla_response_hours=None, sla_resolution_hours=None,
        target_audience="填写指引：写服务对象，如全体员工/仅研发部门；SLA 两栏留空=使用全局策略，特殊承诺才填",
    )
    db.add(item)
    db.flush()

    # ---------- 供应商与合同 ----------
    vendor = Vendor(
        is_example=True, code="VD-DEMO", name="【示例】华信云科技有限公司",
        contact="张经理（填写指引：写对接人姓名+称谓）", phone="021-88886666", email="support@example.com",
        service_scope="填写指引：写清楚该供应商提供的服务范围，如：云资源、数据库维保、驻场支持",
        rating="A",
        remarks="填写指引：评级 A-D 由年度评估得出；备注可记录合作历史与注意事项",
    )
    db.add(vendor)
    db.flush()
    db.add(Contract(
        is_example=True, code="CT-DEMO", name="【示例】数据库年度维保合同",
        vendor_id=vendor.id, amount_10k=36.0,
        start_date=today.replace(month=1, day=1), end_date=today.replace(month=12, day=31),
        owner=person.id,
        remarks="填写指引：金额单位为万元；到期前 90 天系统会自动预警到总览告警区，并通知负责人",
    ))

    # ---------- CMDB ----------
    db.add(Ci(
        is_example=True, ci_code="CI-DEMO", name="【示例】ERP 应用服务器", category="服务器",
        status="运行中", owner=person.id, environment="生产",
        business_owner="填写指引：写业务侧负责人姓名", vendor_id=vendor.id,
        description="填写指引：描述该配置项的用途与位置，如：ERP 生产应用服务器，机房 A-3 机柜",
        launch_date=today - timedelta(days=200),
        attrs={"IP": "10.0.0.10", "配置": "8C32G（填写指引：类别专属属性按需添加键值，如服务器记录 IP/配置，应用记录技术栈）"},
        remarks="填写指引：CI 关系（运行于/依赖/连接）在详情页影响分析中维护，用于故障影响评估",
    ))

    # ---------- 工单：事件（已解决，展示全生命周期字段） ----------
    db.add(Ticket(
        is_example=True, ticket_code="TK-DEMO-001",
        title="【示例】OA 系统无法登录", ticket_type="incident", priority="P2",
        description=(
            "填写指引——描述请包含四要素：\n"
            "① 现象：打开 OA 提示 504 网关超时\n"
            "② 影响范围：行政部约 30 人无法办公\n"
            "③ 已尝试：清缓存、换浏览器均无效\n"
            "④ 期望：尽快恢复访问"
        ),
        service_item_id=item.id, assignee=person.id,
        remarks="填写指引：备注可补充截图链接、方便联系的时段等",
        status="resolved", submitter=None, submitter_name="【示例】业务用户", submitter_dept="行政部",
        service_line=catalog.name,
        submitted_at=now - timedelta(hours=6), first_response_at=now - timedelta(hours=5, minutes=45),
        resolved_at=now - timedelta(hours=2),
        sla_response_min=60, sla_resolution_hours=8,
        actual_response_min=15, actual_resolution_hours=4,
        sla_response_met=True, sla_resolution_met=True, first_time_fix=True,
        solution="填写指引：解决方案写处置动作+验证结果，如：重启应用池并扩容连接数，请用户复测确认恢复",
        root_cause="填写指引：根因写技术层面的真正原因，如：连接池耗尽；若为重复性问题请点「升级为问题」",
    ))
    db.flush()

    # ---------- 工单：变更（已批准待实施，展示变更专属字段与审批） ----------
    db.add(Ticket(
        is_example=True, ticket_code="TK-DEMO-002",
        title="【示例】生产数据库版本升级", ticket_type="change", priority="P2",
        description="填写指引：变更描述写清楚变更对象、内容与业务影响窗口",
        service_item_id=item.id, assignee=person.id,
        change_type="普通", risk_level="中",
        change_reason="填写指引：变更原因写驱动因素，如：官方版本停止安全更新，需升级至受支持版本",
        rollback_plan="填写指引：回退方案必填且要可执行，如：保留旧版本容器镜像与全量备份，30 分钟内可回切",
        implementation_plan="填写指引：实施方案写步骤与验证点，如：①停应用→②备份→③升级→④业务验证清单",
        planned_start_at=now + timedelta(days=2), planned_end_at=now + timedelta(days=2, hours=4),
        status="approved", submitter=None, submitter_name="【示例】王小明",
        service_line=catalog.name, submitted_at=now - timedelta(days=1),
        first_response_at=now - timedelta(hours=20),
        sla_response_min=60, sla_resolution_hours=8, actual_response_min=30, sla_response_met=True,
        approved_at=now - timedelta(hours=3),
        approval_comment="填写指引：审批意见写批准条件，如：同意在周六窗口执行，实施前完成备份并通知业务方",
    ))

    # ---------- 问题（已知错误，关联示例工单） ----------
    demo_ticket = db.query(Ticket).filter(Ticket.ticket_code == "TK-DEMO-001").first()
    problem = Problem(
        is_example=True, problem_code="PB-DEMO-001",
        title="【示例】OA 高峰期频繁出现连接超时",
        description="填写指引：问题描述聚焦重复发生的现象与规律，如：每周一 9:00-10:00 高峰期出现，已有 3 张关联工单",
        priority="P2", status="known_error", owner=person.id,
        root_cause="填写指引：根因分析结论，如：连接池上限 100 低于高峰并发 150；转「已知错误」时必填",
        workaround="填写指引：临时规避方案，如：高峰期前预扩容连接池到 200，重启应用释放连接",
        source_ticket_id=demo_ticket.id if demo_ticket else None,
    )
    db.add(problem)
    db.flush()
    if demo_ticket:
        db.add(ProblemTicket(problem_id=problem.id, ticket_id=demo_ticket.id))

    # ---------- 知识库（发布态，内容本身就是写作指引） ----------
    db.add(KnowledgeArticle(
        is_example=True, article_code="KB-DEMO-001",
        title="【示例】如何写一篇高质量的知识文章",
        content=(
            "# 如何写一篇高质量的知识文章\n\n"
            "> 本文是示例数据：正文用 Markdown 编写，本文结构即推荐模板。\n\n"
            "## 适用场景\n\n一句话说明什么情况下应参考本文（读者判断相关性的依据）。\n\n"
            "## 处理步骤\n\n1. 步骤要可执行、可复制（含命令/路径/截图链接）\n2. 每步写清预期结果\n3. 有风险的步骤标注注意事项\n\n"
            "## 验证方法\n\n写明如何确认问题已解决。\n\n"
            "## 常见坑\n\n- 记录踩过的坑，别人不再踩\n\n"
            "## 相关链接\n\n- 关联工单：在编辑页选择关联工单，读者可回看处理过程\n"
        ),
        content_format="markdown", status="published", tags=["示例", "写作指引"],
        author=None, author_name="系统示例",
    ))

    # ---------- 项目组合与项目 ----------
    portfolio = Portfolio(
        is_example=True, name="【示例】2026 数字化转型组合", owner_id=person.id, year="2026",
        description="填写指引：组合是项目的战略分组（如按年度/按战略方向），项目创建时可挂到组合下统一查看",
        sort=99,
    )
    db.add(portfolio)
    db.flush()
    project = Project(
        is_example=True, project_code="PJ-DEMO-001",
        name="【示例】数据中台建设项目", pm=person.id, status="active",
        planned_start=today - timedelta(days=20), planned_end=today + timedelta(days=40),
        actual_start=today - timedelta(days=20),
        portfolio_id=portfolio.id, service_item_id=item.id, budget_10k=100.0,
        description=(
            "填写指引——项目描述建议包含：\n"
            "① 背景：为什么做（数据口径不一致，重复建设严重）\n"
            "② 目标：做成什么样（统一数仓与指标服务上线）\n"
            "③ 范围：边界在哪（一期覆盖销售与库存域，不含财务）\n"
            "提示：也可以用「章程导入」上传 .docx 自动生成项目+WBS+里程碑+风险"
        ),
        latest_update="填写指引：最新动态一句话（本周完成数仓建模评审，下周开始 ETL 开发）——随时可改，让管理层扫一眼即知进展",
    )
    db.add(project)
    db.flush()
    t1 = WbsTask(
        is_example=True, project_id=project.id, wbs_code="1", stage="1.调研", name="【示例】需求调研与建模",
        assignee=person.id, start_date=today - timedelta(days=20), end_date=today - timedelta(days=8),
        actual_start=today - timedelta(days=20), actual_end=today - timedelta(days=8),
        progress=100, completed_at=now - timedelta(days=8),
        wbs_dict="填写指引：写清含/不含，厘清工作包边界（含数据调研与建模；不含平台搭建）",
        deliverable="填写指引：交付物/DoD 写可检查的验收标准，如：调研纪要+数据模型设计文档签字",
        remarks="填写指引：备注写补充说明",
        sort=0,
    )
    db.add(t1)
    db.flush()
    db.add(WbsTask(
        is_example=True, project_id=project.id, wbs_code="2", stage="2.建设", name="【示例】平台搭建与 ETL 开发（里程碑）",
        assignee=person.id, start_date=today - timedelta(days=7), end_date=today + timedelta(days=20),
        actual_start=today - timedelta(days=7),
        progress=50, is_milestone=True,
        wbs_dict="含数仓环境搭建与首批 ETL；不含报表开发",
        deliverable="可用的数仓环境与首批 ETL 作业（一期上线里程碑）",
        remarks="填写指引：勾选『里程碑=是』的行会自动汇总到里程碑跟踪页；前置任务画甘特图依赖箭头",
        predecessor_ids=[t1.id], sort=1,
    ))
    db.add(Milestone(
        is_example=True, project_id=project.id, name="【示例】一期上线",
        target_date=today + timedelta(days=40),
        description="填写指引：里程碑是关键节点（评审通过/上线/验收），逾期未达成会自动进入总览告警并通知项目经理",
    ))
    db.add(Risk(
        is_example=True, project_id=project.id,
        title="【示例】关键数据源接口延期风险",
        probability="中", impact="高",
        mitigation="填写指引：应对措施要具体可执行，如：提前两周与源系统团队确认接口规格，准备模拟数据兜底",
    ))
    db.add(CostEntry(
        is_example=True, project_id=project.id, entry_date=today - timedelta(days=5),
        amount_10k=12.5, note="填写指引：成本按发生记流水（外包费/云资源/采购），执行率与 CPI 自动计算",
    ))

    # ---------- 需求（实现中，挂接示例项目） ----------
    requirement = Requirement(
        is_example=True, requirement_code="RQ-DEMO-001",
        title="【示例】门店销售日报自动化", req_type="数据",
        business_domain_id=domain.id,
        description=(
            "填写指引——需求描述建议包含：\n"
            "① 现状与痛点：门店每天手工汇总 Excel，耗时 2 小时且易错\n"
            "② 期望：每天 9 点前自动生成日报推送\n"
            "③ 涉及范围：全国 120 家门店的销售与库存数据"
        ),
        source="业务部门", requester=None, requester_name="【示例】业务用户",
        moscow="M", owner=person.id, target_date=today + timedelta(days=30),
        solution="填写指引：解决方案由产品经理在分析阶段填写，写方案要点与技术路线，如：基于数据中台指标服务生成报表，飞书机器人推送",
        acceptance_criteria=[
            {"text": "填写指引：验收标准要可验证——报表口径与财务系统一致（误差为 0）", "checked": True},
            {"text": "每日 9:00 前自动送达（连续 5 个工作日验证）", "checked": False},
        ],
        project_id=project.id,
        status="implementing",
        registered_at=now - timedelta(days=10), analyzing_at=now - timedelta(days=8),
        implementing_at=now - timedelta(days=3),
        remarks="填写指引：验收标准未全部勾选时无法关闭；关闭时可一键转出遗留问题（进问题管理）与经验沉淀（进知识库）",
    )
    db.add(requirement)
    db.flush()
    db.add(RequirementTask(
        is_example=True, requirement_id=requirement.id, name="【示例】指标口径确认",
        assignee=person.id, plan_date=today - timedelta(days=1), status="已完成",
        done_at=now - timedelta(days=1),
    ))
    db.add(RequirementTask(
        is_example=True, requirement_id=requirement.id, name="【示例】报表开发与推送配置",
        assignee=person.id, plan_date=today + timedelta(days=10), status="进行中",
    ))

    db.commit()


def run_seed_team_examples(db: Session):
    """M6：示例专项活动 + 示例建言（业务示例只读）。"""
    from datetime import date, timedelta

    from app.models import ActivityCampaign, CampaignTask, Idea

    if db.query(ActivityCampaign).filter(ActivityCampaign.is_example.is_(True)).first():
        return
    from app.services.perf import period_range
    from app.services.points import current_period

    today = date.today()
    period = current_period()
    p_start, p_end = period_range(period)
    half_start, half_end = p_start.date(), p_end.date()

    campaign = ActivityCampaign(
        is_example=True,
        name="【示例】团建活动方案策划",
        description=(
            "填写指引——活动说明建议包含：\n"
            "① 活动目的：征集下季度团建方案，提升团队凝聚力\n"
            "② 参与方式：任何成员均可提交方案/参与评选/协助执行\n"
            "③ 积分规则：完成下方激励任务由管理员核实后发放积分\n"
            "④ 绩效折算：本活动折算系数 0.1，即活动积分 × 0.1 计入 " + period + " 考核期绩效分\n"
            "（示例：拿满 105 分 → 绩效加 10.5 分）"
        ),
        period_label=period, start_date=half_start, end_date=half_end,
        performance_ratio=0.1, status="active",
    )
    db.add(campaign)
    db.flush()
    tasks = [
        ("提交完整团建方案", "填写指引：贡献指标要可核实——方案含预算明细、日程安排、场地备选；由管理员核实后发放", 30, 1),
        ("方案被评选采纳", "填写指引：结果型指标分值应高于过程型——最终被采纳执行的方案额外奖励", 50, 1),
        ("参与方案投票与评论反馈", "填写指引：轻量参与型任务用低分+多次数鼓励广泛参与（每次 5 分，最多 3 次）", 5, 3),
        ("活动现场组织与执行贡献", "填写指引：执行型贡献按实际承担核发（物料/签到/摄影/主持等，每项 20 分，最多 2 项）", 20, 2),
    ]
    for idx, (name, desc, points, max_times) in enumerate(tasks):
        db.add(CampaignTask(is_example=True, campaign_id=campaign.id, name=name,
                            description=desc, points=points, max_times=max_times, sort=idx))

    if not db.query(Idea).filter(Idea.is_example.is_(True)).first():
        db.add(Idea(
            is_example=True, idea_code="ID-DEMO-001",
            title="【示例】建议引入自动化巡检脚本减少手工检查",
            content=(
                "填写指引——建言内容建议包含：\n"
                "① 现状问题：每天早上人工检查 12 个系统状态，耗时约 40 分钟\n"
                "② 建议方案：用脚本定时巡检并推送异常告警\n"
                "③ 预期收益：每人每天节省 30 分钟，异常发现提前到分钟级\n"
                "提示：提出建言 +2 分；被点赞每次 +1 分；被管理员采纳 +20 分（分值可在积分规则中调整）"
            ),
            proposer=None, proposer_name="系统示例", status="submitted", like_count=0,
        ))
    db.commit()
