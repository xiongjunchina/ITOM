import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  InputNumber,
  Popconfirm,
  Select,
  Switch,
  Table,
  TreeSelect,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlusOutlined, SaveOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { DEPT_TYPE_LABELS, PROVISION_MATCH_LABELS } from '../../api/types';
import type {
  Department,
  DeptType,
  ProvisionMatchType,
  ProvisionRule,
  RoleDef,
} from '../../api/types';
import { buildDeptTreeSelectData } from '../../utils/dept';

interface RuleRow {
  _key: string;
  match_type: ProvisionMatchType;
  match_value: string;
  default_roles: string[];
  sort: number;
  active: boolean;
}

let keySeq = 0;
const nextKey = () => `rule-${++keySeq}`;

const MATCH_TYPE_OPTIONS = (Object.keys(PROVISION_MATCH_LABELS) as ProvisionMatchType[]).map(
  (k) => ({ value: k, label: PROVISION_MATCH_LABELS[k] }),
);

const DEPT_TYPE_VALUE_OPTIONS = (Object.keys(DEPT_TYPE_LABELS) as DeptType[]).map((k) => ({
  value: k,
  label: DEPT_TYPE_LABELS[k],
}));

export default function ProvisionRules() {
  const [rows, setRows] = useState<RuleRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [roleDefs, setRoleDefs] = useState<RoleDef[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<ProvisionRule>('/admin/provision-rules');
      setRows(
        res.items.map((r) => ({
          _key: nextKey(),
          match_type: r.match_type,
          match_value: r.match_value,
          default_roles: r.default_roles ?? [],
          sort: r.sort ?? 0,
          active: r.active,
        })),
      );
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
      .getList<Department>('/admin/departments')
      .then((res) => setDepartments(res.items))
      .catch(() => undefined);
    api
      .getList<RoleDef>('/admin/roles')
      .then((res) => setRoleDefs(res.items))
      .catch(() => undefined);
  }, []);

  const deptTreeData = useMemo(() => buildDeptTreeSelectData(departments), [departments]);

  const roleOptions = useMemo(
    // admin 不允许作为开通默认角色（后端同样校验）
    () => roleDefs.filter((r) => r.code !== 'admin').map((r) => ({ value: r.code, label: r.name })),
    [roleDefs],
  );

  const updateRow = (key: string, patch: Partial<RuleRow>) => {
    setRows((prev) => prev.map((r) => (r._key === key ? { ...r, ...patch } : r)));
  };

  const handleSave = async () => {
    if (rows.some((r) => !r.match_value)) {
      message.error('存在未填写匹配值的规则行，请补全后再保存');
      return;
    }
    setSaving(true);
    try {
      await api.put(
        '/admin/provision-rules',
        rows.map((r) => ({
          match_type: r.match_type,
          match_value: r.match_value,
          default_roles: r.default_roles,
          sort: r.sort,
          active: r.active,
        })),
      );
      message.success('预分配规则已保存');
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<RuleRow> = [
    {
      title: '匹配类型',
      dataIndex: 'match_type',
      width: 160,
      render: (_, record) => (
        <Select
          style={{ width: '100%' }}
          value={record.match_type}
          options={MATCH_TYPE_OPTIONS}
          onChange={(v: ProvisionMatchType) =>
            updateRow(record._key, { match_type: v, match_value: '' })
          }
        />
      ),
    },
    {
      title: '匹配值',
      dataIndex: 'match_value',
      width: 220,
      render: (_, record) =>
        record.match_type === 'dept_type' ? (
          <Select
            style={{ width: '100%' }}
            value={record.match_value || undefined}
            placeholder="选择部门类型"
            options={DEPT_TYPE_VALUE_OPTIONS}
            onChange={(v: string) => updateRow(record._key, { match_value: v })}
          />
        ) : (
          <TreeSelect
            style={{ width: '100%' }}
            value={record.match_value || undefined}
            placeholder="选择部门"
            showSearch
            treeDefaultExpandAll
            treeNodeFilterProp="title"
            treeData={deptTreeData}
            onChange={(v: string) => updateRow(record._key, { match_value: v })}
          />
        ),
    },
    {
      title: '默认角色',
      dataIndex: 'default_roles',
      render: (_, record) => (
        <Select
          mode="multiple"
          style={{ width: '100%' }}
          value={record.default_roles}
          placeholder="选择默认角色"
          optionFilterProp="label"
          options={roleOptions}
          onChange={(v: string[]) => updateRow(record._key, { default_roles: v })}
        />
      ),
    },
    {
      title: '排序',
      dataIndex: 'sort',
      width: 100,
      render: (_, record) => (
        <InputNumber
          value={record.sort}
          min={0}
          onChange={(v) => updateRow(record._key, { sort: v ?? 0 })}
        />
      ),
    },
    {
      title: '启用',
      dataIndex: 'active',
      width: 90,
      align: 'center',
      render: (_, record) => (
        <Switch
          checked={record.active}
          onChange={(checked) => updateRow(record._key, { active: checked })}
        />
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_, record) => (
        <Popconfirm
          title="删除该规则行？"
          onConfirm={() => setRows((prev) => prev.filter((r) => r._key !== record._key))}
        >
          <Button type="link" size="small" danger>
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <Card
      title="预分配规则"
      extra={
        <Button
          type="primary"
          icon={<SaveOutlined />}
          loading={saving}
          onClick={() => void handleSave()}
        >
          保存
        </Button>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="规则仅在账号首次开通时赋默认角色；之后角色可自由增减，用户永远可持有多个角色"
      />
      <Table<RuleRow>
        rowKey="_key"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
      />
      <Button
        type="dashed"
        block
        icon={<PlusOutlined />}
        style={{ marginTop: 8 }}
        onClick={() =>
          setRows((prev) => [
            ...prev,
            {
              _key: nextKey(),
              match_type: 'dept_type',
              match_value: '',
              default_roles: [],
              sort: prev.length > 0 ? Math.max(...prev.map((r) => r.sort)) + 1 : 1,
              active: true,
            },
          ])
        }
      >
        添加规则
      </Button>
    </Card>
  );
}
