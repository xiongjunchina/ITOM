from datetime import date

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6)
    roles: list[str] = []
    person_id: str | None = None
    is_active: bool = True


class UserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=6)
    roles: list[str] | None = None
    person_id: str | None = None
    is_active: bool | None = None


class MemberCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    name_en: str | None = None
    employee_no: str | None = None
    gender: str | None = None
    birth_date: date | None = None
    employment_type: str | None = None
    supervisor_id: str | None = None
    work_location: str | None = None
    department_id: str | None = None
    position_id: str | None = None
    status: str = "在岗"
    hire_date: date | None = None
    email: str | None = None
    mobile: str | None = None
    skills: list[str] = []
    remarks: str | None = None


class MemberUpdate(BaseModel):
    name: str | None = None
    name_en: str | None = None
    employee_no: str | None = None
    gender: str | None = None
    birth_date: date | None = None
    employment_type: str | None = None
    supervisor_id: str | None = None
    work_location: str | None = None
    department_id: str | None = None
    position_id: str | None = None
    status: str | None = None
    hire_date: date | None = None
    email: str | None = None
    mobile: str | None = None
    skills: list[str] | None = None
    remarks: str | None = None


class PositionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    position_code: str | None = Field(default=None, max_length=32)
    position_family: str | None = Field(default=None, max_length=32)
    duties: str | None = None
    headcount: int = 0
    service_domains: list[str] = []
    primary_roles: list[str] = []
    level_framework: str | None = Field(default=None, max_length=64)
    location_scope: str | None = Field(default=None, max_length=128)
    skills: str | None = None
    contractor_allowed: bool = False
    status: str = Field(default="启用", pattern="^(启用|停用)$")
    sort: int = 0


class PositionUpdate(BaseModel):
    name: str | None = None
    position_code: str | None = Field(default=None, max_length=32)
    position_family: str | None = Field(default=None, max_length=32)
    duties: str | None = None
    headcount: int | None = None
    service_domains: list[str] | None = None
    primary_roles: list[str] | None = None
    level_framework: str | None = Field(default=None, max_length=64)
    location_scope: str | None = Field(default=None, max_length=128)
    skills: str | None = None
    contractor_allowed: bool | None = None
    status: str | None = Field(default=None, pattern="^(启用|停用)$")
    sort: int | None = None


class MasterDataCreate(BaseModel):
    category: str
    code: str
    name: str
    sort: int = 0
    active: bool = True


class MasterDataUpdate(BaseModel):
    name: str | None = None
    sort: int | None = None
    active: bool | None = None
