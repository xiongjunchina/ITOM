import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Key, ReactNode } from 'react';
import {
  Alert,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Switch,
  Tag,
  Tooltip,
  Tree,
  TreeSelect,
  message,
} from 'antd';
import type { DataNode } from 'antd/es/tree';
import {
  ApartmentOutlined,
  BankOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  SyncOutlined,
  TeamOutlined,
  UserAddOutlined,
  UserOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import type { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import { hasPermission, useAuthStore } from '../../stores/auth';
import { DEPT_TYPE_COLORS, DEPT_TYPE_LABELS } from '../../api/types';
import type {
  Department,
  DeptType,
  Member,
  OrgTreeData,
  OrgTreeDept,
  Position,
} from '../../api/types';
import { buildDeptTreeSelectData } from '../../utils/dept';

const GRAY = '#999';

const DEPT_TYPE_OPTIONS = (Object.keys(DEPT_TYPE_LABELS) as DeptType[]).map((k) => ({
  value: k,
  label: DEPT_TYPE_LABELS[k],
}));

interface DeptFormValues {
  code?: string;
  name?: string;
  parent_id?: string | null;
  dept_type: DeptType;
  sort?: number;
  active?: boolean;
}

interface MemberFormValues {
  name: string;
  name_en?: string;
  employee_no?: string;
  gender?: string;
  birth_date?: Dayjs | null;
  employment_type?: string;
  supervisor_id?: string;
  work_location?: string;
  department_id?: string;
  position_id?: string;
  status?: '在岗' | '离职';
  hire_date?: Dayjs | null;
  email?: string;
  mobile?: string;
  skills?: string[];
  remarks?: string;
}

/** 选中节点解析结果 */
type Selected =
  | { type: 'none' }
  | { type: 'company' }
  | { type: 'unassigned' }
  | { type: 'dept'; dept: OrgTreeDept }
  | { type: 'member'; member: Member };

/** 同步来源小标签（external_source 非空时原样显示） */
function SourceTag({ source }: { source?: string | null }) {
  if (!source) return null;
  return (
    <Tag
      color="geekblue"
      style={{ marginLeft: 6, fontSize: 11, lineHeight: '16px', padding: '0 4px', verticalAlign: 'middle' }}
    >
      {source}
    </Tag>
  );
}

export default function OrgArchitecture() {
  const user = useAuthStore((s) => s.user);
  const canDeleteMember = hasPermission(user, 'admin_members', 'delete');
  const [data, setData] = useState<OrgTreeData | null>(null);
  const [loading, setLoading] = useState(false);
  const [positions, setPositions] = useState<Position[]>([]);

  const [selectedKey, setSelectedKey] = useState<string | null>('company');
  const [expandedKeys, setExpandedKeys] = useState<Key[]>([]);
  const [autoExpandParent, setAutoExpandParent] = useState(false);
  const [searchValue, setSearchValue] = useState('');
  const initedRef = useRef(false);

  const [syncing, setSyncing] = useState(false);
  const [saving, setSaving] = useState(false);

  const [companyOpen, setCompanyOpen] = useState(false);
  const [companyForm] = Form.useForm<{ name: string }>();

  const [deptModal, setDeptModal] = useState<{ open: boolean; editing: OrgTreeDept | null }>({
    open: false,
    editing: null,
  });
  const [deptForm] = Form.useForm<DeptFormValues>();

  const [memberModal, setMemberModal] = useState<{ open: boolean; editing: Member | null }>({
    open: false,
    editing: null,
  });
  const [memberForm] = Form.useForm<MemberFormValues>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<OrgTreeData>('/admin/org-tree');
      setData(res);
      if (!initedRef.current) {
        initedRef.current = true;
        setExpandedKeys(['company', 'unassigned', ...res.departments.map((d) => `dept:${d.id}`)]);
      }
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    api
      .getList<Position>('/positions', { page: 1, page_size: 999 })
      .then((res) => setPositions(res.items))
      .catch(() => undefined);
  }, []);

  // ---------- 派生数据 ----------

  const deptById = useMemo(
    () => new Map((data?.departments ?? []).map((d) => [d.id, d])),
    [data],
  );

  const allMembers = useMemo(() => {
    const list: Member[] = [];
    for (const d of data?.departments ?? []) list.push(...d.members);
    list.push(...(data?.unassigned_members ?? []));
    return list;
  }, [data]);

  const memberById = useMemo(() => new Map(allMembers.map((m) => [m.id, m])), [allMembers]);

  const deptList = useMemo<Department[]>(
    () => (data?.departments ?? []).map((d) => ({ ...d, member_count: d.members.length })),
    [data],
  );

  const deptTreeSelectData = useMemo(() => buildDeptTreeSelectData(deptList), [deptList]);

  const deptNameOf = useCallback(
    (id?: string | null) => (id ? deptById.get(id)?.name ?? null : null),
    [deptById],
  );

  const selected = useMemo<Selected>(() => {
    if (!selectedKey || !data) return { type: 'none' };
    if (selectedKey === 'company') return { type: 'company' };
    if (selectedKey === 'unassigned') return { type: 'unassigned' };
    if (selectedKey.startsWith('dept:')) {
      const dept = deptById.get(selectedKey.slice(5));
      return dept ? { type: 'dept', dept } : { type: 'none' };
    }
    if (selectedKey.startsWith('member:')) {
      const member = memberById.get(selectedKey.slice(7));
      return member ? { type: 'member', member } : { type: 'none' };
    }
    return { type: 'none' };
  }, [selectedKey, data, deptById, memberById]);

  // ---------- 左树 ----------

  const treeData = useMemo<DataNode[]>(() => {
    if (!data) return [];
    const q = searchValue.trim().toLowerCase();
    const highlight = (text: string): ReactNode => {
      if (!q) return text;
      const idx = text.toLowerCase().indexOf(q);
      if (idx < 0) return text;
      return (
        <>
          {text.slice(0, idx)}
          <span style={{ color: '#f5222d' }}>{text.slice(idx, idx + q.length)}</span>
          {text.slice(idx + q.length)}
        </>
      );
    };

    const memberNode = (m: Member): DataNode => {
      const off = m.status === '离职';
      return {
        key: `member:${m.id}`,
        icon: <UserOutlined />,
        isLeaf: true,
        title: (
          <span style={off ? { color: GRAY } : undefined}>
            {highlight(m.name)}
            {off ? <span style={{ color: GRAY }}>（离职）</span> : null}
            <SourceTag source={m.external_source} />
          </span>
        ),
      };
    };

    const ids = new Set(data.departments.map((d) => d.id));
    const byParent = new Map<string | null, OrgTreeDept[]>();
    for (const d of data.departments) {
      const pid = d.parent_id && ids.has(d.parent_id) ? d.parent_id : null;
      byParent.set(pid, [...(byParent.get(pid) ?? []), d]);
    }
    const deptNodes = (pid: string | null): DataNode[] =>
      (byParent.get(pid) ?? [])
        .slice()
        .sort((a, b) => (a.sort ?? 0) - (b.sort ?? 0) || a.code.localeCompare(b.code))
        .map((d) => ({
          key: `dept:${d.id}`,
          icon: <ApartmentOutlined />,
          title: (
            <span style={!d.active ? { color: GRAY } : undefined}>
              {highlight(d.name)}
              {!d.active ? <span style={{ color: GRAY }}>（停用）</span> : null}
              <SourceTag source={d.external_source} />
            </span>
          ),
          children: [...deptNodes(d.id), ...d.members.map(memberNode)],
        }));

    const children: DataNode[] = deptNodes(null);
    if (data.unassigned_members.length > 0) {
      children.push({
        key: 'unassigned',
        icon: <TeamOutlined />,
        title: <span style={{ color: GRAY }}>{highlight('未分配部门')}</span>,
        children: data.unassigned_members.map(memberNode),
      });
    }
    return [
      {
        key: 'company',
        icon: <BankOutlined />,
        title: <span style={{ fontWeight: 600 }}>{highlight(data.company.name)}</span>,
        children,
      },
    ];
  }, [data, searchValue]);

  /** 搜索：展开所有命中节点的祖先链并高亮 */
  const onSearchChange = (value: string) => {
    setSearchValue(value);
    const q = value.trim().toLowerCase();
    if (!q || !data) return;
    const hit = (name?: string | null) => !!name && name.toLowerCase().includes(q);
    const expanded = new Set<Key>(['company']);
    const ids = new Set(data.departments.map((d) => d.id));
    const parentOf = new Map(data.departments.map((d) => [d.id, d.parent_id]));
    const expandChain = (deptId?: string | null) => {
      let cur = deptId ?? null;
      while (cur && ids.has(cur)) {
        expanded.add(`dept:${cur}`);
        cur = parentOf.get(cur) ?? null;
      }
    };
    for (const d of data.departments) {
      if (hit(d.name)) expandChain(d.parent_id);
      if (d.members.some((m) => hit(m.name))) expandChain(d.id);
    }
    if (data.unassigned_members.some((m) => hit(m.name))) expanded.add('unassigned');
    setExpandedKeys([...expanded]);
    setAutoExpandParent(true);
  };

  // ---------- 同步 ----------

  const handleSync = async () => {
    if (!data || data.sync_sources.length === 0) return;
    setSyncing(true);
    try {
      await api.post('/admin/org-sync', { source: data.sync_sources[0] });
      message.success('同步完成');
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSyncing(false);
    }
  };

  // ---------- 公司 ----------

  const openCompanyEdit = () => {
    companyForm.setFieldsValue({ name: data?.company.name ?? '' });
    setCompanyOpen(true);
  };

  const handleCompanySave = async () => {
    const values = await companyForm.validateFields();
    if (!data?.company.master_data_id) return;
    setSaving(true);
    try {
      await api.patch(`/admin/master-data/${data.company.master_data_id}`, { name: values.name });
      message.success('公司名称已更新');
      setCompanyOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  // ---------- 部门 ----------

  const openDeptCreate = (parentId: string | null) => {
    setDeptModal({ open: true, editing: null });
    deptForm.resetFields();
    deptForm.setFieldsValue({ parent_id: parentId ?? undefined, dept_type: 'it', sort: 0 });
  };

  const openDeptEdit = (dept: OrgTreeDept) => {
    setDeptModal({ open: true, editing: dept });
    deptForm.setFieldsValue({
      code: dept.code,
      name: dept.name,
      parent_id: dept.parent_id ?? undefined,
      dept_type: dept.dept_type,
      sort: dept.sort,
      active: dept.active,
    });
  };

  const handleDeptSave = async () => {
    const values = await deptForm.validateFields();
    setSaving(true);
    try {
      if (deptModal.editing) {
        const dept = deptModal.editing;
        // 同步部门仅可修改部门类型，其余字段以外部源为准
        const payload = dept.external_source
          ? { dept_type: values.dept_type }
          : {
              name: values.name,
              parent_id: values.parent_id ?? null,
              dept_type: values.dept_type,
              sort: values.sort ?? 0,
              active: values.active ?? true,
            };
        await api.patch(`/admin/departments/${dept.id}`, payload);
        message.success('部门已更新');
      } else {
        await api.post('/admin/departments', {
          code: values.code,
          name: values.name,
          parent_id: values.parent_id ?? null,
          dept_type: values.dept_type,
          sort: values.sort ?? 0,
        });
        message.success('部门已创建');
      }
      setDeptModal({ open: false, editing: null });
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const handleDeptDelete = async (dept: OrgTreeDept) => {
    try {
      await api.delete(`/admin/departments/${dept.id}`);
      message.success('部门已删除');
      setSelectedKey('company');
      void load();
    } catch {
      // 有人员或下级时后端返回中文错误，已统一提示
    }
  };

  // ---------- 人员 ----------

  const openMemberCreate = () => {
    setMemberModal({ open: true, editing: null });
    memberForm.resetFields();
    memberForm.setFieldsValue({
      status: '在岗',
      // 选中部门时预填部门
      department_id: selected.type === 'dept' ? selected.dept.id : undefined,
    });
  };

  const openMemberEdit = (m: Member) => {
    setMemberModal({ open: true, editing: m });
    memberForm.setFieldsValue({
      name: m.name,
      name_en: m.name_en ?? undefined,
      employee_no: m.employee_no ?? undefined,
      gender: m.gender ?? undefined,
      birth_date: m.birth_date ? dayjs(m.birth_date) : undefined,
      employment_type: m.employment_type ?? undefined,
      supervisor_id: m.supervisor_id ?? undefined,
      work_location: m.work_location ?? undefined,
      department_id: m.department_id ?? undefined,
      position_id: m.position_id ?? undefined,
      status: m.status ?? undefined,
      hire_date: m.hire_date ? dayjs(m.hire_date) : undefined,
      email: m.email ?? undefined,
      mobile: m.mobile ?? undefined,
      skills: m.skills ?? undefined,
      remarks: m.remarks ?? undefined,
    });
  };

  const handleMemberSave = async () => {
    const values = await memberForm.validateFields();
    const localPart = {
      position_id: values.position_id ?? null,
      skills: values.skills ?? [],
      remarks: values.remarks ?? null,
    };
    const hrPart = {
      name: values.name,
      name_en: values.name_en ?? null,
      employee_no: values.employee_no ?? null,
      gender: values.gender ?? null,
      birth_date: values.birth_date ? values.birth_date.format('YYYY-MM-DD') : null,
      employment_type: values.employment_type ?? null,
      supervisor_id: values.supervisor_id ?? null,
      work_location: values.work_location ?? null,
      department_id: values.department_id ?? null,
      status: values.status,
      hire_date: values.hire_date ? values.hire_date.format('YYYY-MM-DD') : null,
      email: values.email ?? null,
      mobile: values.mobile ?? null,
    };
    setSaving(true);
    try {
      if (memberModal.editing) {
        const m = memberModal.editing;
        // 同步人员：仅提交岗位/技能/备注，锁定字段以外部源为准（后端 SYNCED_READONLY 强制）
        await api.patch(
          `/members/${m.id}`,
          m.external_source ? localPart : { ...hrPart, ...localPart },
        );
        message.success('人员信息已更新');
      } else {
        await api.post('/members', { ...hrPart, ...localPart });
        message.success('人员已创建');
      }
      setMemberModal({ open: false, editing: null });
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  /** 删除人员（软删）：绑定账号一并停用；SYNCED_READONLY / MEMBER_HAS_OPEN_WORK 由拦截器提示 */
  const handleMemberDelete = async (m: Member) => {
    try {
      const res = await api.delete<{ message?: string }>(`/members/${m.id}`);
      message.success(res?.message || '人员已删除');
      setSelectedKey(null);
      void load();
    } catch {
      // 已统一提示
    }
  };

  const supervisorOptions = useMemo(
    () =>
      allMembers
        .filter((m) => m.id !== memberModal.editing?.id)
        .map((m) => ({
          value: m.id,
          label: `${m.name}（${deptNameOf(m.department_id) ?? '未分配'}）`,
        })),
    [allMembers, memberModal.editing, deptNameOf],
  );

  // ---------- 右侧面板 ----------

  const renderCompanyPanel = () => {
    if (!data) return null;
    return (
      <>
        <Descriptions
          title="公司信息"
          bordered
          size="small"
          column={1}
          extra={
            data.company.master_data_id ? (
              <Button icon={<EditOutlined />} onClick={openCompanyEdit}>
                编辑
              </Button>
            ) : (
              <Tooltip title="公司名称字典项（sys_config / company_name）缺失，请先在数据字典中创建">
                <Button icon={<EditOutlined />} disabled>
                  编辑
                </Button>
              </Tooltip>
            )
          }
        >
          <Descriptions.Item label="公司名称">{data.company.name}</Descriptions.Item>
        </Descriptions>
        <Alert
          type="info"
          showIcon
          style={{ marginTop: 12 }}
          message="将来接入飞书后组织架构以飞书为准"
        />
      </>
    );
  };

  const renderDeptPanel = (dept: OrgTreeDept) => {
    const synced = !!dept.external_source;
    return (
      <>
        {synced && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message={`该部门由 ${dept.external_source} 同步，结构以外部源为准，本地仅可修改“部门类型”`}
          />
        )}
        <Descriptions
          title="部门信息"
          bordered
          size="small"
          column={2}
          extra={
            <Space>
              <Button icon={<EditOutlined />} onClick={() => openDeptEdit(dept)}>
                编辑
              </Button>
              <Button icon={<PlusOutlined />} onClick={() => openDeptCreate(dept.id)}>
                新建子部门
              </Button>
              {!synced && (
                <Popconfirm title="确定删除该部门？" onConfirm={() => void handleDeptDelete(dept)}>
                  <Button danger icon={<DeleteOutlined />}>
                    删除
                  </Button>
                </Popconfirm>
              )}
            </Space>
          }
        >
          <Descriptions.Item label="编码">{dept.code}</Descriptions.Item>
          <Descriptions.Item label="名称">{dept.name}</Descriptions.Item>
          <Descriptions.Item label="类型">
            <Tag color={DEPT_TYPE_COLORS[dept.dept_type]}>{DEPT_TYPE_LABELS[dept.dept_type]}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="排序">{dept.sort}</Descriptions.Item>
          <Descriptions.Item label="启用">
            {dept.active ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>}
          </Descriptions.Item>
          <Descriptions.Item label="同步来源">{dept.external_source || '本地维护'}</Descriptions.Item>
          <Descriptions.Item label="人数">{dept.members.length}</Descriptions.Item>
          <Descriptions.Item label="上级部门">
            {deptNameOf(dept.parent_id) ?? '（顶级部门）'}
          </Descriptions.Item>
        </Descriptions>
      </>
    );
  };

  const renderMemberPanel = (m: Member) => {
    const synced = !!m.external_source;
    return (
      <>
        {synced && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message={`人员主数据以 ${m.external_source} 为准，同步维护；本地仅可编辑岗位/技能/备注`}
          />
        )}
        <Descriptions
          title="HR 基础信息"
          bordered
          size="small"
          column={2}
          extra={
            <Space>
              <Button icon={<EditOutlined />} onClick={() => openMemberEdit(m)}>
                编辑
              </Button>
              {canDeleteMember && (
                <Popconfirm
                  title="删除后该人员将不可见，其绑定的登录账号会一并停用。确认删除？"
                  onConfirm={() => void handleMemberDelete(m)}
                >
                  <Button danger icon={<DeleteOutlined />}>
                    删除人员
                  </Button>
                </Popconfirm>
              )}
            </Space>
          }
        >
          <Descriptions.Item label="姓名">{m.name}</Descriptions.Item>
          <Descriptions.Item label="英文名">{m.name_en || '-'}</Descriptions.Item>
          <Descriptions.Item label="工号">{m.employee_no || '-'}</Descriptions.Item>
          <Descriptions.Item label="性别">{m.gender || '-'}</Descriptions.Item>
          <Descriptions.Item label="出生日期">{m.birth_date || '-'}</Descriptions.Item>
          <Descriptions.Item label="用工类型">{m.employment_type || '-'}</Descriptions.Item>
          <Descriptions.Item label="直属上级">{m.supervisor_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="办公地点">{m.work_location || '-'}</Descriptions.Item>
          <Descriptions.Item label="部门">{deptNameOf(m.department_id) ?? '未分配'}</Descriptions.Item>
          <Descriptions.Item label="入职日期">{m.hire_date || '-'}</Descriptions.Item>
          <Descriptions.Item label="邮箱">{m.email || '-'}</Descriptions.Item>
          <Descriptions.Item label="手机">{m.mobile || '-'}</Descriptions.Item>
          <Descriptions.Item label="状态">
            {m.status ? <Tag color={m.status === '在岗' ? 'green' : 'default'}>{m.status}</Tag> : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="同步来源">{m.external_source || '本地维护'}</Descriptions.Item>
        </Descriptions>
        <Descriptions title="IT 扩展信息" bordered size="small" column={2} style={{ marginTop: 16 }}>
          <Descriptions.Item label="岗位">{m.position_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="技能">
            {(m.skills ?? []).length > 0
              ? (m.skills ?? []).map((s) => <Tag key={s}>{s}</Tag>)
              : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>
            {m.remarks || '-'}
          </Descriptions.Item>
        </Descriptions>
      </>
    );
  };

  const renderPanel = () => {
    if (!data) return null;
    switch (selected.type) {
      case 'company':
        return renderCompanyPanel();
      case 'dept':
        return renderDeptPanel(selected.dept);
      case 'member':
        return renderMemberPanel(selected.member);
      case 'unassigned':
        return (
          <Alert
            type="info"
            showIcon
            message={`共 ${data.unassigned_members.length} 人未分配部门`}
            description="编辑人员档案并选择部门后，将自动归入相应部门。"
          />
        );
      default:
        return <Empty description="请在左侧选择公司、部门或人员查看详情" style={{ marginTop: 48 }} />;
    }
  };

  // ---------- 渲染 ----------

  const syncConfigured = (data?.sync_sources.length ?? 0) > 0;
  const deptSynced = !!deptModal.editing?.external_source;
  const memberSynced = !!memberModal.editing?.external_source;

  return (
    <Card
      title="组织架构"
      extra={
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            刷新
          </Button>
          {syncConfigured ? (
            <Button icon={<SyncOutlined />} loading={syncing} onClick={() => void handleSync()}>
              从飞书同步
            </Button>
          ) : (
            <Tooltip title="飞书同步将于上线前配置凭据后启用">
              <Button icon={<SyncOutlined />} disabled>
                从飞书同步
              </Button>
            </Tooltip>
          )}
        </Space>
      }
    >
      <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
        <div style={{ width: 320, flexShrink: 0 }}>
          <Input.Search
            placeholder="搜索部门 / 人员名称"
            allowClear
            onChange={(e) => onSearchChange(e.target.value)}
            style={{ marginBottom: 8 }}
          />
          <Spin spinning={loading}>
            <div style={{ maxHeight: 640, overflow: 'auto' }}>
              <Tree
                showIcon
                treeData={treeData}
                selectedKeys={selectedKey ? [selectedKey] : []}
                onSelect={(keys) => setSelectedKey(keys.length > 0 ? String(keys[0]) : null)}
                expandedKeys={expandedKeys}
                autoExpandParent={autoExpandParent}
                onExpand={(keys) => {
                  setExpandedKeys(keys);
                  setAutoExpandParent(false);
                }}
              />
            </div>
          </Spin>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Space style={{ marginBottom: 16 }}>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openDeptCreate(null)}>
              新建部门
            </Button>
            <Button icon={<UserAddOutlined />} onClick={openMemberCreate}>
              新建人员
            </Button>
          </Space>
          {renderPanel()}
        </div>
      </div>

      {/* 公司名称编辑 */}
      <Modal
        title="编辑公司名称"
        open={companyOpen}
        onOk={() => void handleCompanySave()}
        confirmLoading={saving}
        onCancel={() => setCompanyOpen(false)}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="将来接入飞书后组织架构以飞书为准"
        />
        <Form form={companyForm} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label="公司名称"
            rules={[{ required: true, message: '请输入公司名称' }]}
          >
            <Input maxLength={100} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 部门新建 / 编辑 */}
      <Modal
        title={deptModal.editing ? '编辑部门' : '新建部门'}
        open={deptModal.open}
        onOk={() => void handleDeptSave()}
        confirmLoading={saving}
        onCancel={() => setDeptModal({ open: false, editing: null })}
        destroyOnClose
      >
        {deptSynced && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="该部门由飞书同步，结构以外部源为准，仅可修改部门类型"
          />
        )}
        <Form<DeptFormValues> form={deptForm} layout="vertical" preserve={false}>
          <Form.Item
            name="code"
            label="编码"
            rules={
              deptModal.editing
                ? []
                : [
                    { required: true, message: '请输入部门编码' },
                    { pattern: /^[a-zA-Z0-9_.-]{2,32}$/, message: '2-32 位字母、数字、下划线、点或中划线' },
                  ]
            }
          >
            <Input maxLength={32} disabled={!!deptModal.editing} placeholder="如 it.ops" />
          </Form.Item>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入部门名称' }]}
          >
            <Input maxLength={50} disabled={deptSynced} />
          </Form.Item>
          <Form.Item name="parent_id" label="上级部门">
            <TreeSelect
              allowClear
              showSearch
              treeDefaultExpandAll
              treeNodeFilterProp="title"
              placeholder="不选则为顶级部门"
              treeData={buildDeptTreeSelectData(deptList, deptModal.editing?.id)}
              disabled={deptSynced}
            />
          </Form.Item>
          <Space.Compact block>
            <Form.Item
              name="dept_type"
              label="类型"
              style={{ width: '50%', marginRight: 8 }}
              rules={[{ required: true, message: '请选择部门类型' }]}
            >
              <Select options={DEPT_TYPE_OPTIONS} />
            </Form.Item>
            <Form.Item name="sort" label="排序" style={{ width: '50%' }}>
              <InputNumber min={0} style={{ width: '100%' }} disabled={deptSynced} />
            </Form.Item>
          </Space.Compact>
          {deptModal.editing && (
            <Form.Item name="active" label="启用" valuePropName="checked">
              <Switch checkedChildren="启用" unCheckedChildren="停用" disabled={deptSynced} />
            </Form.Item>
          )}
        </Form>
      </Modal>

      {/* 人员新建 / 编辑 */}
      <Modal
        title={memberModal.editing ? '编辑人员' : '新建人员'}
        open={memberModal.open}
        onOk={() => void handleMemberSave()}
        confirmLoading={saving}
        onCancel={() => setMemberModal({ open: false, editing: null })}
        destroyOnClose
        width={640}
      >
        {memberSynced && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message="人员主数据以飞书为准，同步维护；仅岗位/技能/备注可本地编辑"
          />
        )}
        <Form<MemberFormValues> form={memberForm} layout="vertical" preserve={false}>
          <Space.Compact block>
            <Form.Item
              name="name"
              label="中文姓名"
              style={{ width: '50%', marginRight: 8 }}
              rules={[{ required: true, message: '请输入中文姓名' }]}
            >
              <Input maxLength={50} disabled={memberSynced} />
            </Form.Item>
            <Form.Item name="name_en" label="英文名" style={{ width: '50%' }}>
              <Input maxLength={50} placeholder="如 Zhang San" disabled={memberSynced} />
            </Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item name="employee_no" label="工号" style={{ width: '50%', marginRight: 8 }}>
              <Input maxLength={32} disabled={memberSynced} />
            </Form.Item>
            <Form.Item name="gender" label="性别" style={{ width: '50%' }}>
              <Select
                allowClear
                disabled={memberSynced}
                options={[
                  { value: '男', label: '男' },
                  { value: '女', label: '女' },
                ]}
              />
            </Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item name="birth_date" label="出生日期" style={{ width: '50%', marginRight: 8 }}>
              <DatePicker style={{ width: '100%' }} disabled={memberSynced} />
            </Form.Item>
            <Form.Item name="employment_type" label="用工类型" style={{ width: '50%' }}>
              <Select
                allowClear
                disabled={memberSynced}
                options={[
                  { value: '正式', label: '正式' },
                  { value: '外包', label: '外包' },
                  { value: '实习', label: '实习' },
                ]}
              />
            </Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item name="supervisor_id" label="直属上级" style={{ width: '50%', marginRight: 8 }}>
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="从人员列表中选择"
                options={supervisorOptions}
                disabled={memberSynced}
              />
            </Form.Item>
            <Form.Item name="work_location" label="办公地点" style={{ width: '50%' }}>
              <Input maxLength={100} disabled={memberSynced} />
            </Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item name="department_id" label="部门" style={{ width: '50%', marginRight: 8 }}>
              <TreeSelect
                allowClear
                showSearch
                treeDefaultExpandAll
                treeNodeFilterProp="title"
                placeholder="从部门树中选择"
                treeData={deptTreeSelectData}
                disabled={memberSynced}
              />
            </Form.Item>
            <Form.Item name="position_id" label="岗位" style={{ width: '50%' }}>
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="从岗位编制中选择"
                options={positions.map((p) => ({ value: p.id, label: p.name }))}
              />
            </Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item name="status" label="状态" style={{ width: '50%', marginRight: 8 }}>
              <Select
                disabled={memberSynced}
                options={[
                  { value: '在岗', label: '在岗' },
                  { value: '离职', label: '离职' },
                ]}
              />
            </Form.Item>
            <Form.Item name="hire_date" label="入职日期" style={{ width: '50%' }}>
              <DatePicker style={{ width: '100%' }} disabled={memberSynced} />
            </Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item
              name="email"
              label="邮箱"
              style={{ width: '50%', marginRight: 8 }}
              rules={[{ type: 'email', message: '邮箱格式不正确' }]}
            >
              <Input maxLength={100} disabled={memberSynced} />
            </Form.Item>
            <Form.Item name="mobile" label="手机" style={{ width: '50%' }}>
              <Input maxLength={20} disabled={memberSynced} />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="skills" label="技能标签">
            <Select mode="tags" placeholder="输入后回车添加" open={false} suffixIcon={null} />
          </Form.Item>
          <Form.Item name="remarks" label="备注">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
