"""供应商与合同（PRD §5.6）。合同状态实时推导：生效/临期(90天)/已过期。"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError, ensure_example_delete_allowed, ensure_not_example
from app.db import get_db
from app.deps import get_current_user, require_perm
from app.models import AuthUser, Ci, Contract, OrgMember, Vendor
from app.schemas.common import ok, paginate
from app.services.audit import audit
from app.services.codes import gen_code
from app.services.team_scope import require_it_member_if_configured

router = APIRouter(tags=["itsm"])

EXPIRY_WARN_DAYS = 90


class VendorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    contact: str | None = None
    phone: str | None = None
    email: str | None = None
    service_scope: str | None = None
    rating: str | None = None
    remarks: str | None = None


class VendorUpdate(VendorCreate):
    name: str | None = None
    status: str | None = None


class ContractCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    vendor_id: str
    start_date: date
    end_date: date
    amount_10k: float | None = None
    owner: str | None = None
    remarks: str | None = None


class ContractUpdate(BaseModel):
    name: str | None = None
    vendor_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    amount_10k: float | None = None
    owner: str | None = None
    remarks: str | None = None


def contract_status(c: Contract) -> str:
    today = date.today()
    if c.end_date < today:
        return "已过期"
    if c.end_date <= today + timedelta(days=EXPIRY_WARN_DAYS):
        return "临期"
    if c.start_date > today:
        return "未生效"
    return "生效"


def _vendor_row(v: Vendor, db: Session) -> dict:
    contracts = db.query(Contract).filter(Contract.vendor_id == v.id, Contract.is_deleted.is_(False)).count()
    cis = db.query(Ci).filter(Ci.vendor_id == v.id, Ci.is_deleted.is_(False)).count()
    return {
        "id": v.id, "code": v.code, "name": v.name, "is_example": v.is_example, "contact": v.contact, "phone": v.phone,
        "email": v.email, "service_scope": v.service_scope, "rating": v.rating,
        "status": v.status, "remarks": v.remarks,
        "contract_count": contracts, "ci_count": cis,
    }


def _contract_row(c: Contract, db: Session) -> dict:
    owner = db.get(OrgMember, c.owner) if c.owner else None
    return {
        "id": c.id, "code": c.code, "name": c.name, "is_example": c.is_example,
        "vendor_id": c.vendor_id, "vendor_name": c.vendor.name if c.vendor else None,
        "amount_10k": c.amount_10k, "start_date": c.start_date, "end_date": c.end_date,
        "owner": c.owner, "owner_name": owner.name if owner else None,
        "status": contract_status(c), "remarks": c.remarks,
        "days_to_expiry": (c.end_date - date.today()).days,
    }


@router.get("/api/vendors")
def list_vendors(page: int = 1, page_size: int = 20, q: str = "", db: Session = Depends(get_db), _: AuthUser = Depends(require_perm("vendors", "view"))):
    query = db.query(Vendor).filter(Vendor.is_deleted.is_(False))
    if q:
        query = query.filter(Vendor.name.ilike(f"%{q}%"))
    items, total = paginate(query.order_by(Vendor.is_example.desc(), Vendor.created_at.desc()), page, page_size)
    return ok([_vendor_row(v, db) for v in items], total=total, page=page)


@router.post("/api/vendors")
def create_vendor(body: VendorCreate, db: Session = Depends(get_db), actor=Depends(require_perm("vendors", "create"))):
    vendor = Vendor(**body.model_dump(), code=gen_code(db, Vendor, "code", "VD"))
    db.add(vendor)
    db.flush()
    audit(db, "vendor", vendor.id, "create", actor, {"name": body.name})
    db.commit()
    return ok(_vendor_row(vendor, db))


@router.patch("/api/vendors/{vendor_id}")
def update_vendor(vendor_id: str, body: VendorUpdate, db: Session = Depends(get_db), actor=Depends(require_perm("vendors", "edit"))):
    vendor = db.get(Vendor, vendor_id)
    if not vendor or vendor.is_deleted:
        raise AppError("NOT_FOUND", "供应商不存在", 404)
    ensure_not_example(vendor)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(vendor, k, v)
    audit(db, "vendor", vendor.id, "update", actor, {"fields": list(data.keys())})
    db.commit()
    return ok(_vendor_row(vendor, db))


@router.delete("/api/vendors/{vendor_id}")
def delete_vendor(vendor_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("vendors", "delete"))):
    """删除供应商（M21，软删）：名下仍有合同时拒绝，先删除或转移合同。"""
    vendor = db.get(Vendor, vendor_id)
    if not vendor or vendor.is_deleted:
        raise AppError("NOT_FOUND", "供应商不存在", 404)
    ensure_example_delete_allowed(vendor, db, actor)
    live_contracts = db.query(Contract).filter(Contract.vendor_id == vendor.id, Contract.is_deleted.is_(False)).all()
    if live_contracts:
        if vendor.is_example and all(contract.is_example for contract in live_contracts):
            for contract in live_contracts:
                contract.is_deleted = True
        else:
            raise AppError("VENDOR_IN_USE", f"该供应商名下还有 {len(live_contracts)} 份合同，请先删除或转移合同")
    vendor.is_deleted = True
    audit(db, "vendor", vendor.id, "delete", actor, {"code": vendor.code, "name": vendor.name, "contracts_deleted": len(live_contracts) if vendor.is_example else 0})
    db.commit()
    return ok({"id": vendor.id})


@router.get("/api/contracts")
def list_contracts(page: int = 1, page_size: int = 20, q: str = "", vendor_id: str = "", db: Session = Depends(get_db), _: AuthUser = Depends(require_perm("contracts", "view"))):
    query = db.query(Contract).filter(Contract.is_deleted.is_(False))
    if q:
        query = query.filter(Contract.name.ilike(f"%{q}%"))
    if vendor_id:
        query = query.filter(Contract.vendor_id == vendor_id)
    items, total = paginate(query.order_by(Contract.is_example.desc(), Contract.end_date), page, page_size)
    return ok([_contract_row(c, db) for c in items], total=total, page=page)


@router.post("/api/contracts")
def create_contract(body: ContractCreate, db: Session = Depends(get_db), actor=Depends(require_perm("contracts", "create"))):
    if body.end_date <= body.start_date:
        raise AppError("INVALID_DATES", "结束日期必须晚于开始日期")
    if not db.get(Vendor, body.vendor_id):
        raise AppError("NOT_FOUND", "供应商不存在", 404)
    require_it_member_if_configured(db, body.owner, "合同负责人")
    contract = Contract(**body.model_dump(), code=gen_code(db, Contract, "code", "CT"))
    db.add(contract)
    db.flush()
    audit(db, "contract", contract.id, "create", actor, {"name": body.name})
    db.commit()
    return ok(_contract_row(contract, db))


@router.patch("/api/contracts/{contract_id}")
def update_contract(contract_id: str, body: ContractUpdate, db: Session = Depends(get_db), actor=Depends(require_perm("contracts", "edit"))):
    contract = db.get(Contract, contract_id)
    if not contract or contract.is_deleted:
        raise AppError("NOT_FOUND", "合同不存在", 404)
    ensure_not_example(contract)
    data = body.model_dump(exclude_unset=True)
    if "owner" in data:
        require_it_member_if_configured(db, data["owner"], "合同负责人")
    if "end_date" in data and data["end_date"] != contract.end_date:
        contract.expiry_warned = False  # 续签后重置预警
    for k, v in data.items():
        setattr(contract, k, v)
    audit(db, "contract", contract.id, "update", actor, {"fields": list(data.keys())})
    db.commit()
    return ok(_contract_row(contract, db))


@router.delete("/api/contracts/{contract_id}")
def delete_contract(contract_id: str, db: Session = Depends(get_db), actor=Depends(require_perm("contracts", "delete"))):
    """删除合同（M21，软删；delete 权限默认仅 admin）。"""
    contract = db.get(Contract, contract_id)
    if not contract or contract.is_deleted:
        raise AppError("NOT_FOUND", "合同不存在", 404)
    ensure_example_delete_allowed(contract, db, actor)
    contract.is_deleted = True
    audit(db, "contract", contract.id, "delete", actor, {"code": contract.code, "name": contract.name})
    db.commit()
    return ok({"id": contract.id})
