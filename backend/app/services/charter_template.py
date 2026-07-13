"""生成项目章程模板 .docx（零依赖，直接拼 OOXML）。

模板结构与 app/services/charter.py 解析器严格对应：
- 2 列信息表（项目名称/项目经理/计划开始/计划完成/项目预算）
- 段落节 1.项目背景 / 3.项目目标 / 4.1 项目包含范围
- 5 列表格，首列 M1/M2… → WBS + 里程碑
- 7.1 关键风险节内 5 列表格（概率/影响列填 高/中/低）
标签中英双语（解析器按中文锚点 contains 匹配）；填入示例值，项目经理替换后即可导入。
"""
from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/></Relationships>'
)


def _para(text: str, bold: bool = False, size: int | None = None) -> str:
    rpr = ""
    if bold or size:
        rpr = "<w:rPr>" + ("<w:b/>" if bold else "") + (f'<w:sz w:val="{size}"/>' if size else "") + "</w:rPr>"
    return f'<w:p><w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def _cell(text: str) -> str:
    return (
        '<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/>'
        '<w:tcBorders>'
        '<w:top w:val="single" w:sz="4" w:color="999999"/>'
        '<w:left w:val="single" w:sz="4" w:color="999999"/>'
        '<w:bottom w:val="single" w:sz="4" w:color="999999"/>'
        '<w:right w:val="single" w:sz="4" w:color="999999"/>'
        "</w:tcBorders></w:tcPr>"
        f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p></w:tc>'
    )


def _table(rows: list[list[str]]) -> str:
    tbl_pr = (
        '<w:tblPr><w:tblW w:w="0" w:type="auto"/>'
        '<w:tblBorders>'
        '<w:top w:val="single" w:sz="4" w:color="999999"/>'
        '<w:left w:val="single" w:sz="4" w:color="999999"/>'
        '<w:bottom w:val="single" w:sz="4" w:color="999999"/>'
        '<w:right w:val="single" w:sz="4" w:color="999999"/>'
        '<w:insideH w:val="single" w:sz="4" w:color="999999"/>'
        '<w:insideV w:val="single" w:sz="4" w:color="999999"/>'
        "</w:tblBorders></w:tblPr>"
    )
    trs = "".join("<w:tr>" + "".join(_cell(c) for c in row) + "</w:tr>" for row in rows)
    return f"<w:tbl>{tbl_pr}{trs}</w:tbl>"


def build_charter_template_docx() -> bytes:
    body: list[str] = []
    body.append(_para("项目章程模板 / Project Charter Template", bold=True, size=32))
    body.append(_para(
        "填写说明：替换下方示例内容后，通过「项目管理 → 项目列表 → 导入章程」上传本文件即可自动创建项目。"
        " / Replace the sample text below, then upload this file via Projects → Project List → Import Charter.",
    ))
    body.append(_para(""))

    # 信息表（2 列，label|value）
    body.append(_table([
        ["项目名称 / Project Name", "示例：客户门户升级项目"],
        ["项目经理（IT 部）/ Project Manager", "示例：张三"],
        ["计划开始 / Planned Start (YYYY-MM-DD)", "2026-08-01"],
        ["计划完成 / Planned End (YYYY-MM-DD)", "2026-12-31"],
        ["项目预算 / Budget (万元 / 10k CNY)", "50"],
    ]))
    body.append(_para(""))

    # 描述节（解析器按 1.项目背景 / 3.项目目标 / 4.1 项目包含范围 抓取；编号连贯完整）
    body.append(_para("1. 项目背景 / Project Background", bold=True))
    body.append(_para("示例：现有客户门户上线 5 年，技术栈老旧、体验差，需整体升级以支撑业务增长。"))
    body.append(_para("2. 相关方 / Stakeholders", bold=True))
    body.append(_para("示例：业务部门（需求方）、IT 开发与运维团队、外部供应商。"))
    body.append(_para("3. 项目目标 / Project Goals", bold=True))
    body.append(_para("示例：门户改版按期上线，核心功能可用率 99.9%，用户满意度 ≥ 90%。"))
    body.append(_para("4. 项目范围 / Scope", bold=True))
    body.append(_para("4.1 项目包含范围 / In-scope", bold=True))
    body.append(_para("示例：门户前端重构、SSO 集成、3 个核心业务模块迁移。"))
    body.append(_para("4.2 项目不包含范围 / Out-of-scope", bold=True))
    body.append(_para("示例：后端数据库迁移、移动端 App（另立项目）。"))
    body.append(_para(""))

    # 5. WBS 任务分解（层级由 WBS编号 建立，前置任务按 WBS编号 引用，勾里程碑=是 汇总到里程碑跟踪）
    body.append(_para(
        "5. WBS 任务分解与里程碑 / Work Breakdown Structure & Milestones"
        "（层级由 WBS编号 建立(1/1.1)；前置任务、里程碑均随行填写 / hierarchy by WBS code; predecessors by code）",
        bold=True,
    ))
    body.append(_table([
        ["阶段 Stage", "WBS编号 Code", "任务名称(交付物) Task", "WBS词典说明(含/不含) Dictionary",
         "交付物/验收标准(DoD)", "责任人 Owner", "里程碑 Milestone(是/否)", "前置任务(WBS号) Predecessors",
         "计划开始 Start (YYYY-MM-DD)", "计划结束 End (YYYY-MM-DD)"],
        ["1.需求", "1", "需求与设计", "含需求调研与建模；不含开发", "需求规格说明书签字", "张三", "否", "", "2026-08-01", "2026-08-31"],
        ["1.需求", "1.1", "需求调研", "访谈与现状分析", "调研报告", "张三", "否", "", "2026-08-01", "2026-08-15"],
        ["1.需求", "1.2", "方案设计", "原型与技术方案", "设计文档评审通过", "李四", "否", "1.1", "2026-08-16", "2026-08-31"],
        ["2.开发", "2", "开发实现", "含前端重构与接口开发；不含数据迁移", "可运行系统（里程碑）", "李四", "是", "1.2", "2026-09-01", "2026-11-15"],
        ["3.上线", "3", "测试上线", "系统测试与上线部署", "上线验收报告（里程碑）", "王五", "是", "2", "2026-11-16", "2026-12-31"],
    ]))
    body.append(_para(
        "填写说明：WBS编号用层级式(1/1.1/1.1.1)，父级由编号前缀自动推导；前置任务填被依赖任务的 WBS编号；"
        "里程碑列填『是』的行会自动汇总到系统「里程碑跟踪」页；实际开始/结束、完成度% 在执行阶段于系统内更新。"
        " / WBS code is hierarchical; predecessors reference codes; rows marked 是 (yes) become milestones; "
        "actual dates & completion % are updated in the app during execution."))
    body.append(_para(""))

    # 6. 预算与资源（预算金额在顶部信息表填写；此处描述资源投入）
    body.append(_para("6. 预算与资源 / Budget & Resources", bold=True))
    body.append(_para("示例：总预算见文首信息表；投入 1 名 PM、3 名开发、1 名测试，外部供应商配合 UI 设计。"))
    body.append(_para(""))

    # 7. 风险与应对（7.1 关键风险表：概率/影响列填 高/中/低）
    body.append(_para("7. 风险与应对 / Risk Management", bold=True))
    body.append(_para("7.1 关键风险 / Key Risks（概率、影响列请填 高/中/低 / probability & impact: 高/中/低）", bold=True))
    body.append(_table([
        ["风险类别 Category", "风险描述 Description", "概率 Prob", "影响 Impact", "应对措施 Mitigation"],
        ["技术风险", "新技术栈团队不熟悉，影响开发效率", "中", "高", "提前培训与技术预研"],
        ["进度风险", "需求变更导致工期延误", "高", "中", "变更控制流程 + 预留缓冲期"],
    ]))
    body.append(_para("7.2 应对与监控 / Monitoring", bold=True))
    body.append(_para("示例：每周风险复盘，红色风险升级至项目发起人。"))
    body.append(_para(""))

    # 9. 审批
    body.append(_para("8. 审批 / Approval", bold=True))
    body.append(_table([
        ["角色 Role", "姓名 Name", "签字/日期 Sign / Date"],
        ["项目发起人 Sponsor", "", ""],
        ["项目经理 Project Manager", "", ""],
    ]))

    sect = '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>'
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>{"".join(body)}{sect}</w:body></w:document>'
    )

    buf = BytesIO()
    with ZipFile(buf, "w", ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", document)
    return buf.getvalue()
