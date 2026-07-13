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
    return "".join(t.text or "" for t in p.iter(f"{{{W_NS['w']}}}t")).strip()


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

    def section(heading_pattern: str) -> str | None:
        collected = []
        active = False
        for ln in lines:
            if re.match(heading_pattern, ln):
                active = True
                continue
            if active:
                if re.match(r"^\d+(\.\d+)*[\.、\s]", ln) or "\t" in ln:
                    break
                collected.append(ln)
        return " ".join(collected)[:1000] or None

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
    description_parts = []
    for label, pattern in (("项目背景", r"^1[\.、]\s*项目背景"), ("项目目标", r"^3[\.、]\s*项目目标"), ("项目范围", r"^4\.1\s*项目包含范围")):
        content = section(pattern)
        if content:
            description_parts.append(f"{label}：{content}")
    fields["description"] = "\n".join(description_parts) or None

    # 三张表按结构区分（位置化单元格，保留空列）：里程碑 3 列 / WBS 8 列 / 风险 5 列
    wbs, milestones, risks = [], [], []
    for ln in lines:
        cells = [c.strip() for c in ln.split("\t")]
        if len(cells) == 8 and _normalize_date(cells[2]) and cells[0]:  # WBS 数据行（开始日期列为日期；表头自动跳过）
            name, assignee, start, end, parent, preds, deliverable, desc = cells
            wbs.append({
                "name": name, "assignee_name": assignee or None,
                "start_date": _normalize_date(start), "end_date": _normalize_date(end),
                "parent_name": parent or None, "predecessor_names": preds or None,
                "deliverable": deliverable or None, "description": desc or None,
            })
        elif len(cells) == 3 and _normalize_date(cells[1]) and cells[0]:  # 里程碑数据行（目标日期列）
            milestones.append({"name": cells[0], "target_date": _normalize_date(cells[1]), "description": cells[2] or None})
        elif len(cells) == 5 and cells[2] in ("高", "中", "低"):  # 风险数据行（概率列 高/中/低；表头自动跳过）
            category, rdesc, prob, impact, mitigation = cells
            risks.append({"title": f"{category}：{rdesc}"[:200], "probability": prob, "impact": impact, "mitigation": mitigation})

    warnings = []
    for key, label in (("name", "项目名称"), ("pm_name", "项目经理"), ("planned_start", "计划开始"), ("planned_end", "计划完成")):
        if not fields.get(key):
            warnings.append(f"未解析到「{label}」，请手工补充")
    if not wbs:
        warnings.append("未解析到 WBS 任务表（第 6 节，8 列）")
    if not milestones:
        warnings.append("未解析到里程碑表（第 5 节，3 列）")
    if not risks:
        warnings.append("未解析到风险表（8.1 关键风险，5 列）")

    return {"fields": fields, "drafts": {"wbs": wbs[:50], "milestones": milestones[:20], "risks": risks[:10]}, "warnings": warnings}
