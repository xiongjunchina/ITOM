"""ITSM 批量导入（M3.10）：服务目录/CMDB/供应商/合同 的模板导出与 Excel 导入。

语义：逐行校验，有效行入库、失败行带行号原因返回（部分成功）；
重复判定按名称（目录/服务项/CI/供应商）或 名称+供应商（合同），重复行报错不覆盖。
"""
from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import get_db
from app.deps import require_perm
from app.models import Ci, Contract, OrgMember, ServiceCatalog, ServiceItem, Vendor
from app.schemas.common import ok
from app.services.audit import audit
from app.services.codes import gen_code
from app.services.excel_io import Col, Sheet, build_template, parse_sheet

router = APIRouter(prefix="/api/itsm-import", tags=["itsm"])

MAX_XLSX = 5 * 1024 * 1024

CI_CATEGORIES = ["应用", "服务器", "云资源", "网络", "安全", "协作", "终端", "基础设施", "咨询"]

CATALOG_SHEETS = [
    Sheet("服务目录", [
        Col("name", "目录名称", required=True),
        Col("tier", "分级", enum=["gold", "silver", "bronze"], hint="金牌 gold / 银牌 silver / 铜牌 bronze"),
        Col("description", "描述"),
        Col("sort", "排序", kind="int"),
    ]),
    Sheet("服务项", [
        Col("name", "服务项名称", required=True),
        Col("catalog_name", "所属目录名称", required=True, hint="须与「服务目录」表中的目录名称一致（或系统已有目录）"),
        Col("service_type", "服务类型"),
        Col("owner_name", "负责人姓名", hint="须为系统中已有人员，找不到时留空导入"),
        Col("description", "描述"),
        Col("sla_response_hours", "SLA响应(小时)", kind="float", hint="留空=使用全局策略"),
        Col("sla_resolution_hours", "SLA解决(小时)", kind="float", hint="留空=使用全局策略"),
        Col("target_audience", "服务对象"),
    ]),
]

CI_SHEET = Sheet("配置项", [
    Col("name", "名称", required=True),
    Col("category", "类别", required=True, enum=CI_CATEGORIES),
    Col("owner_name", "技术负责人姓名", required=True, hint="须为系统中已有在岗人员"),
    Col("product_manager_name", "应用产品经理姓名", hint="仅类别为应用时可填写且必填；须为系统中已有在岗人员"),
    Col("status", "状态", enum=["运行中", "维护中", "已下线"], hint="留空默认运行中"),
    Col("environment", "环境", enum=["生产", "测试", "开发"]),
    Col("business_owner", "业务负责人"),
    Col("vendor_name", "供应商名称", hint="须为系统中已有供应商，找不到时留空导入"),
    Col("description", "描述"),
    Col("launch_date", "上线日期", kind="date"),
    Col("remarks", "备注"),
])

VENDOR_SHEET = Sheet("供应商", [
    Col("name", "名称", required=True),
    Col("contact", "联系人"),
    Col("phone", "电话"),
    Col("email", "邮箱"),
    Col("service_scope", "服务范围"),
    Col("rating", "评级", enum=["A", "B", "C", "D"]),
    Col("remarks", "备注"),
])

CONTRACT_SHEET = Sheet("合同", [
    Col("name", "合同名称", required=True),
    Col("vendor_name", "供应商名称", required=True, hint="须为系统中已有供应商（可先导入供应商）"),
    Col("amount_10k", "金额(万元)", kind="float"),
    Col("start_date", "开始日期", required=True, kind="date"),
    Col("end_date", "结束日期", required=True, kind="date"),
    Col("owner_name", "负责人姓名", hint="须为系统中已有人员，找不到时留空导入"),
    Col("remarks", "备注"),
])


def _xlsx_response(content: bytes, filename: str) -> Response:
    from urllib.parse import quote

    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=template.xlsx; filename*=UTF-8''{quote(filename)}"
        },
    )


async def _read_xlsx(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) > MAX_XLSX:
        raise AppError("FILE_TOO_LARGE", "导入文件不能超过 5MB")
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise AppError("INVALID_FORMAT", "请上传 .xlsx 文件（使用系统导出的模板）")
    return content


def _member_by_name(db: Session) -> dict[str, str]:
    return {
        m.name: m.id
        for m in db.query(OrgMember).filter(OrgMember.is_deleted.is_(False), OrgMember.status == "在岗")
    }


# ---------- 服务目录（目录 + 服务项 双 sheet） ----------

@router.get("/catalog/template")
def catalog_template(_=Depends(require_perm("catalog", "create"))):
    return _xlsx_response(build_template(CATALOG_SHEETS), "服务目录导入模板.xlsx")


@router.post("/catalog")
async def import_catalog(file: UploadFile, db: Session = Depends(get_db), actor=Depends(require_perm("catalog", "create"))):
    content = await _read_xlsx(file)
    cat_rows, cat_errors = parse_sheet(content, CATALOG_SHEETS[0])
    item_rows, item_errors = parse_sheet(content, CATALOG_SHEETS[1])
    errors = [{**e, "sheet": "服务目录"} for e in cat_errors] + [{**e, "sheet": "服务项"} for e in item_errors]
    created = {"catalogs": 0, "items": 0}

    existing_catalogs = {
        c.name: c for c in db.query(ServiceCatalog).filter(ServiceCatalog.is_deleted.is_(False))
    }
    for r in cat_rows:
        if r["name"] in existing_catalogs:
            errors.append({"sheet": "服务目录", "row": r["_row"], "error": f"目录「{r['name']}」已存在，跳过"})
            continue
        catalog = ServiceCatalog(
            code=gen_code(db, ServiceCatalog, "code", "SC"),
            name=r["name"], tier=r.get("tier") or "silver",
            description=r.get("description"), sort=r.get("sort") or 0,
        )
        db.add(catalog)
        db.flush()
        existing_catalogs[catalog.name] = catalog
        created["catalogs"] += 1

    members = _member_by_name(db)
    existing_items = {
        i.name for i in db.query(ServiceItem).filter(ServiceItem.is_deleted.is_(False))
    }
    for r in item_rows:
        if r["name"] in existing_items:
            errors.append({"sheet": "服务项", "row": r["_row"], "error": f"服务项「{r['name']}」已存在，跳过"})
            continue
        catalog = existing_catalogs.get(r["catalog_name"])
        if not catalog:
            errors.append({"sheet": "服务项", "row": r["_row"], "error": f"所属目录「{r['catalog_name']}」不存在"})
            continue
        db.add(ServiceItem(
            item_code=gen_code(db, ServiceItem, "item_code", "SI"),
            name=r["name"], catalog_id=catalog.id,
            service_type=r.get("service_type"),
            owner=members.get(r.get("owner_name") or ""),
            description=r.get("description"),
            sla_response_hours=r.get("sla_response_hours"),
            sla_resolution_hours=r.get("sla_resolution_hours"),
            target_audience=r.get("target_audience"),
        ))
        db.flush()
        existing_items.add(r["name"])
        created["items"] += 1

    audit(db, "service_catalog", "batch", "import", actor, {**created, "failed": len(errors)})
    db.commit()
    return ok({"created": created, "failed": errors})


# ---------- CMDB ----------

@router.get("/ci/template")
def ci_template(_=Depends(require_perm("cmdb", "create"))):
    return _xlsx_response(build_template([CI_SHEET]), "配置项导入模板.xlsx")


@router.post("/ci")
async def import_ci(file: UploadFile, db: Session = Depends(get_db), actor=Depends(require_perm("cmdb", "create"))):
    content = await _read_xlsx(file)
    rows, errors = parse_sheet(content, CI_SHEET)
    members = _member_by_name(db)
    vendors = {v.name: v.id for v in db.query(Vendor).filter(Vendor.is_deleted.is_(False))}
    existing = {c.name for c in db.query(Ci).filter(Ci.is_deleted.is_(False))}
    created = 0
    for r in rows:
        if r["name"] in existing:
            errors.append({"row": r["_row"], "error": f"配置项「{r['name']}」已存在，跳过"})
            continue
        owner = members.get(r["owner_name"])
        if not owner:
            errors.append({"row": r["_row"], "error": f"技术负责人「{r['owner_name']}」不是系统中的在岗人员"})
            continue
        product_manager_name = r.get("product_manager_name")
        product_manager_id = members.get(product_manager_name or "")
        if r["category"] == "应用" and not product_manager_id:
            error = (
                f"应用产品经理「{product_manager_name}」不是系统中的在岗人员"
                if product_manager_name
                else "应用配置项必须填写应用产品经理姓名"
            )
            errors.append({"row": r["_row"], "error": error})
            continue
        if r["category"] != "应用" and product_manager_name:
            errors.append({"row": r["_row"], "error": "应用产品经理姓名仅可填写在类别为应用的配置项中"})
            continue
        db.add(Ci(
            ci_code=gen_code(db, Ci, "ci_code", "CI"),
            name=r["name"], category=r["category"], owner=owner,
            product_manager_id=product_manager_id,
            status=r.get("status") or "运行中",
            environment=r.get("environment"), business_owner=r.get("business_owner"),
            vendor_id=vendors.get(r.get("vendor_name") or ""),
            description=r.get("description"), launch_date=r.get("launch_date"),
            remarks=r.get("remarks"),
        ))
        db.flush()
        existing.add(r["name"])
        created += 1
    audit(db, "ci", "batch", "import", actor, {"created": created, "failed": len(errors)})
    db.commit()
    return ok({"created": created, "failed": errors})


# ---------- 供应商 ----------

@router.get("/vendor/template")
def vendor_template(_=Depends(require_perm("vendors", "create"))):
    return _xlsx_response(build_template([VENDOR_SHEET]), "供应商导入模板.xlsx")


@router.post("/vendor")
async def import_vendor(file: UploadFile, db: Session = Depends(get_db), actor=Depends(require_perm("vendors", "create"))):
    content = await _read_xlsx(file)
    rows, errors = parse_sheet(content, VENDOR_SHEET)
    existing = {v.name for v in db.query(Vendor).filter(Vendor.is_deleted.is_(False))}
    created = 0
    for r in rows:
        if r["name"] in existing:
            errors.append({"row": r["_row"], "error": f"供应商「{r['name']}」已存在，跳过"})
            continue
        db.add(Vendor(
            code=gen_code(db, Vendor, "code", "VD"),
            name=r["name"], contact=r.get("contact"), phone=r.get("phone"),
            email=r.get("email"), service_scope=r.get("service_scope"),
            rating=r.get("rating"), remarks=r.get("remarks"),
        ))
        db.flush()
        existing.add(r["name"])
        created += 1
    audit(db, "vendor", "batch", "import", actor, {"created": created, "failed": len(errors)})
    db.commit()
    return ok({"created": created, "failed": errors})


# ---------- 合同 ----------

@router.get("/contract/template")
def contract_template(_=Depends(require_perm("contracts", "create"))):
    return _xlsx_response(build_template([CONTRACT_SHEET]), "合同导入模板.xlsx")


@router.post("/contract")
async def import_contract(file: UploadFile, db: Session = Depends(get_db), actor=Depends(require_perm("contracts", "create"))):
    content = await _read_xlsx(file)
    rows, errors = parse_sheet(content, CONTRACT_SHEET)
    members = _member_by_name(db)
    vendors = {v.name: v.id for v in db.query(Vendor).filter(Vendor.is_deleted.is_(False))}
    existing = {(c.name, c.vendor_id) for c in db.query(Contract).filter(Contract.is_deleted.is_(False))}
    created = 0
    for r in rows:
        vendor_id = vendors.get(r["vendor_name"])
        if not vendor_id:
            errors.append({"row": r["_row"], "error": f"供应商「{r['vendor_name']}」不存在（可先导入供应商）"})
            continue
        if (r["name"], vendor_id) in existing:
            errors.append({"row": r["_row"], "error": f"合同「{r['name']}」已存在，跳过"})
            continue
        if r["end_date"] < r["start_date"]:
            errors.append({"row": r["_row"], "error": "结束日期早于开始日期"})
            continue
        db.add(Contract(
            code=gen_code(db, Contract, "code", "CT"),
            name=r["name"], vendor_id=vendor_id, amount_10k=r.get("amount_10k"),
            start_date=r["start_date"], end_date=r["end_date"],
            owner=members.get(r.get("owner_name") or ""), remarks=r.get("remarks"),
        ))
        db.flush()
        existing.add((r["name"], vendor_id))
        created += 1
    audit(db, "contract", "batch", "import", actor, {"created": created, "failed": len(errors)})
    db.commit()
    return ok({"created": created, "failed": errors})
