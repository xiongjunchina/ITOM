"""项目章程解析（移植自 SN-AOM project_charter_import.py 核心逻辑，零额外依赖）。

约定的章程 .docx 结构（与原系统模板一致）：
- 表格行「项目名称/项目经理/计划开始/计划完成/项目预算」→ 项目字段
- 段落节「1. 项目背景 / 3. 项目目标 / 4.1 项目包含范围」→ 描述
- 5 列表格行，首列 M1/M2… → WBS 任务 + 里程碑草稿
- 「7.1 关键风险」节内 5 列行（首列以"风险"结尾）→ 风险草稿
"""
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from io import BytesIO
from zipfile import BadZipFile, ZipFile

W_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _paragraph_text(p) -> str:
    """段落文本：<w:t> 拼接；<w:br/>（Shift+Enter 软换行）转 \n，避免两行粘连。"""
    parts: list[str] = []
    for node in p.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "t":
            parts.append(node.text or "")
        elif tag == "br":
            parts.append("\n")
    return "".join(parts).strip()


def extract_docx_text(raw: bytes) -> str:
    """docx → 结构化文本（表格行以 \t 连接单元格）。"""
    try:
        with ZipFile(BytesIO(raw)) as z:
            xml_bytes = z.read("word/document.xml")
    except (BadZipFile, KeyError):
        raise ValueError("不是有效的 .docx 文件")
    body = ET.fromstring(xml_bytes).find("w:body", W_NS)
    if body is None:
        return ""
    blocks: list[str] = []
    for child in body:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            text = _paragraph_text(child)
            if text:
                blocks.append(text)
        elif tag == "tbl":
            for tr in child.findall("w:tr", W_NS):
                cells = ["".join(t.text or "" for t in tc.iter(f"{{{W_NS['w']}}}t")).strip()
                         for tc in tr.findall("w:tc", W_NS)]
                if any(cells):
                    blocks.append("\t".join(cells))
    return "\n".join(blocks)


def _normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip().replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").replace(".", "-")
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def _parse_budget(value: str | None) -> float | None:
    if not value:
        return None
    m = re.search(r"([\d.]+)", str(value).replace(",", ""))
    if not m:
        return None
    amount = float(m.group(1))
    return amount / 10000 if "元" in value and "万" not in value and amount > 10000 else amount


def parse_charter(raw: bytes) -> dict:
    """返回 {fields, drafts:{wbs, milestones, risks}, warnings}。"""
    text = extract_docx_text(raw)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    row_map: dict[str, str] = {}
    for ln in lines:
        cells = [c.strip() for c in ln.split("\t") if c.strip()]
        if len(cells) == 2:
            row_map[cells[0]] = cells[1]
        elif len(cells) == 4:  # 两对 label/value 同行
            row_map[cells[0]] = cells[1]
            row_map[cells[2]] = cells[3]

    # 已知节标题（编号无关：兼容 3./三、/无编号 等写法；短行才算标题，防止正文误判）
    SECTION_TITLES = [
        r"项目背景", r"(项目)?组织与相关方", r"相关方", r"项目目标",
        r"项目范围", r"(项目)?包含范围", r"(项目)?不包含范围",
        r"WBS", r"预算与资源", r"风险与应对", r"关键风险", r"应对与监控", r"审批",
    ]
    _titles = "|".join(SECTION_TITLES)
    # 带编号前缀（3./4.1/六、）+ 标题词 → 直接认标题（编号开头+标题词的行几乎不会是正文）；
    # 无编号裸标题 → 限短行（≤40），防止正文里含标题词的长句被误判为边界
    _numbered_re = re.compile(r"^[\d一二三四五六七八九十]{1,3}(\.\d+)*[\.、\s]+(" + _titles + ")")
    _bare_re = re.compile(r"^(" + _titles + ")")

    def is_heading(ln: str) -> bool:
        if "\t" in ln:
            return False
        if _numbered_re.match(ln):
            return True
        return len(ln) <= 40 and bool(_bare_re.match(ln))

    def section(heading_pattern: str) -> str | None:
        """收集某节标题后的正文，直到下一个已知节标题或表格行。

        边界只认「已知标题/表格」——正文里的编号列表（1. xxx）或数字开头行不再误判为
        下一节而提前截断（M13.1 修复：目标/资源说明常写成编号列表导致解析为空）。
        """
        collected = []
        active = False
        for ln in lines:
            if not active and re.match(heading_pattern, ln):
                active = True
                continue
            if active:
                if "\t" in ln or is_heading(ln):
                    break
                if ln.startswith(("（", "(")):
                    continue  # 模板的括号说明行不入正文
                collected.append(ln)
        return "\n".join(collected)[:2000] or None

    def find(*anchors: str) -> str | None:
        """按锚点 contains 匹配 label（容忍双语/带注释标签，如「项目名称 / Project Name」）。"""
        for key, value in row_map.items():
            if any(a in key for a in anchors):
                return value
        return None

    fields = {
        "name": find("项目名称"),
        "pm_name": find("项目经理"),
        "planned_start": _normalize_date(find("计划开始")),
        "planned_end": _normalize_date(find("计划完成", "计划结束")),
        "budget_10k": _parse_budget(find("项目预算")),
    }
    # 结构化章节（M13）：与概述页分段/章程模板章节一一对应；不再拼接进 description
    _n = r"^[\d一二三四五六七八九十]{0,3}(\.\d+)*[\.、\s]*"  # 可选编号前缀（3./三、/4.1/无编号）
    fields["background"] = section(_n + r"项目背景")
    fields["goals"] = section(_n + r"项目目标")
    fields["scope_in"] = section(_n + r"(项目)?包含范围")
    fields["scope_out"] = section(_n + r"(项目)?不包含范围")
    fields["resource_note"] = section(_n + r"预算与资源")

    # §2 组织与相关方表（4 列：类别|姓名|角色/单位|职责或关注点），按类别分流
    org_members, stakeholders = [], []
    for ln in lines:
        cells = [c.strip() for c in ln.split("\t")]
        if len(cells) == 4 and cells[1] and ("成员" in cells[0] or "干系人" in cells[0]):
            entry = {"name": cells[1], "role": cells[2] or None, "duty": cells[3] or None}
            (org_members if "成员" in cells[0] else stakeholders).append(entry)
    fields["org_members"] = org_members[:50] or None
    fields["stakeholders"] = stakeholders[:50] or None
    fields["description"] = None  # 旧「拼接描述」废弃，结构化字段替代

    # 两张表按结构区分（位置化单元格）：WBS 10 列（含里程碑标志，里程碑=WBS 派生）/ 风险 5 列
    wbs, risks = [], []
    for ln in lines:
        cells = [c.strip() for c in ln.split("\t")]
        if len(cells) == 10 and _normalize_date(cells[8]) and cells[2]:  # WBS 数据行（计划开始列为日期；表头自动跳过）
            stage, code, name, wbs_dict, deliverable, assignee, ms, preds, start, end = cells
            wbs.append({
                "stage": stage or None, "wbs_code": code or None, "name": name,
                "wbs_dict": wbs_dict or None, "deliverable": deliverable or None,
                "assignee_name": assignee or None,
                "is_milestone": ms.strip() in ("是", "Y", "y", "yes", "true", "1"),
                "predecessor_codes": preds or None,
                "start_date": _normalize_date(start), "end_date": _normalize_date(end),
            })
        elif len(cells) == 5 and cells[2] in ("高", "中", "低"):  # 风险数据行（概率列 高/中/低；表头自动跳过）
            category, rdesc, prob, impact, mitigation = cells
            risks.append({"title": f"{category}：{rdesc}"[:200], "probability": prob, "impact": impact, "mitigation": mitigation})

    warnings = []
    for key, label in (("name", "项目名称"), ("pm_name", "项目经理"), ("planned_start", "计划开始"), ("planned_end", "计划完成")):
        if not fields.get(key):
            warnings.append(f"未解析到「{label}」，请手工补充")
    if not wbs:
        warnings.append("未解析到 WBS 任务表（第 5 节，10 列）")
    if not risks:
        warnings.append("未解析到风险表（7.1 关键风险，5 列）")
    if not fields.get("org_members") and not fields.get("stakeholders"):
        warnings.append("未解析到组织与相关方表（第 2 节，4 列：类别|姓名|角色|职责）")
    for key, label in (("background", "项目背景"), ("goals", "项目目标"),
                       ("scope_in", "包含范围"), ("scope_out", "不包含范围"),
                       ("resource_note", "预算与资源")):
        if not fields.get(key):
            warnings.append(f"未解析到「{label}」章节，可在导入后到项目编辑中补充")

    return {"fields": fields, "drafts": {"wbs": wbs[:100], "risks": risks[:10]}, "warnings": warnings}
