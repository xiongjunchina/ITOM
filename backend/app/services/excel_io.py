"""Excel 模板导出与批量导入通用引擎（M3.10）。

- build_template(): 生成空白 xlsx——首行表头（必填加 *），第二行灰色说明（含枚举提示），列宽自适应
- parse_sheet(): 逐行读取校验——必填/枚举/日期/数字/自定义解析器；返回 (有效行, 错误列表[行号+原因])
- 导入语义：有效行入库、失败行报告（部分成功），重复判定由各实体导入器负责
"""
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter


@dataclass
class Col:
    key: str
    label: str
    required: bool = False
    hint: str = ""
    enum: list[str] | None = None
    kind: str = "str"  # str/float/int/date


@dataclass
class Sheet:
    name: str
    columns: list[Col] = field(default_factory=list)


def build_template(sheets: list[Sheet]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    header_font = Font(bold=True)
    hint_fill = PatternFill("solid", fgColor="F5F5F5")
    hint_font = Font(color="888888", size=10)
    for spec in sheets:
        ws = wb.create_sheet(spec.name)
        for idx, col in enumerate(spec.columns, start=1):
            title = f"*{col.label}" if col.required else col.label
            c = ws.cell(row=1, column=idx, value=title)
            c.font = header_font
            hint = col.hint
            if col.enum:
                hint = (hint + "；" if hint else "") + "可选值：" + "/".join(col.enum)
            if col.kind == "date":
                hint = (hint + "；" if hint else "") + "日期格式 2026-01-31"
            h = ws.cell(row=2, column=idx, value=hint or None)
            h.fill = hint_fill
            h.font = hint_font
            ws.column_dimensions[get_column_letter(idx)].width = max(14, len(title) * 2 + 4)
        ws.freeze_panes = "A3"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _coerce(col: Col, value: Any) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if col.kind == "date":
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
        except ValueError:
            raise ValueError(f"{col.label}：日期格式应为 2026-01-31")
    if col.kind == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{col.label}：应为数字")
    if col.kind == "int":
        try:
            return int(float(value))
        except (TypeError, ValueError):
            raise ValueError(f"{col.label}：应为整数")
    text = str(value).strip()
    if col.enum and text not in col.enum:
        raise ValueError(f"{col.label}：'{text}' 不在可选值 {'/'.join(col.enum)} 中")
    return text


def parse_sheet(file_bytes: bytes, spec: Sheet) -> tuple[list[dict], list[dict]]:
    """返回 (rows, errors)。rows 元素含 _row 行号；说明行(第2行)与空行跳过。"""
    wb = load_workbook(io.BytesIO(file_bytes), data_only=True)
    if spec.name not in wb.sheetnames:
        return [], [{"row": 0, "error": f"缺少工作表「{spec.name}」（请使用系统导出的模板）"}]
    ws = wb[spec.name]
    rows: list[dict] = []
    errors: list[dict] = []
    for row_idx, cells in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if row_idx == 2:  # 说明行
            continue
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in cells):
            continue
        record: dict = {"_row": row_idx}
        row_errors = []
        for idx, col in enumerate(spec.columns):
            raw = cells[idx] if idx < len(cells) else None
            try:
                value = _coerce(col, raw)
            except ValueError as e:
                row_errors.append(str(e))
                continue
            if col.required and value is None:
                row_errors.append(f"{col.label}：必填")
                continue
            record[col.key] = value
        if row_errors:
            errors.append({"row": row_idx, "error": "；".join(row_errors)})
        else:
            rows.append(record)
    return rows, errors
