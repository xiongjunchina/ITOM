import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Divider,
  Input,
  InputNumber,
  Popconfirm,
  Radio,
  Segmented,
  Select,
  Space,
  Switch,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import Table from '../../components/SortableTable';
import { PlusOutlined, SaveOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { WORKFLOW_ENTITY_LABELS } from '../../api/types';
import type {
  RoleDef,
  UserGroup,
  WorkflowConfig as WorkflowConfigData,
  WorkflowEntityType,
} from '../../api/types';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';

interface StatusRow {
  _key: string;
  code: string;
  name: string;
  is_initial: boolean;
  is_terminal: boolean;
  sort: number;
}

interface TransitionRow {
  _key: string;
  from_code: string;
  to_code: string;
  allowed_roles: string[];
}

let keySeq = 0;
const nextKey = () => `row-${++keySeq}`;

export default function WorkflowConfig() {
  const t = useT();
  const et = useEnums();
  const [entityType, setEntityType] = useState<WorkflowEntityType>('ticket');
  const [statuses, setStatuses] = useState<StatusRow[]>([]);
  const [transitions, setTransitions] = useState<TransitionRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const [roleOptions, setRoleOptions] = useState<
    { value: string; label: string }[]
  >([]);

  const load = useCallback(async (et: WorkflowEntityType) => {
    setLoading(true);
    try {
      const data = await api.get<WorkflowConfigData>('/admin/workflow-config', {
        entity_type: et,
      });
      setStatuses(
        (data.statuses ?? []).map((s) => ({
          _key: nextKey(),
          code: s.code,
          name: s.name,
          is_initial: s.is_initial,
          is_terminal: s.is_terminal,
          sort: s.sort,
        })),
      );
      setTransitions(
        (data.transitions ?? []).map((t) => ({
          _key: nextKey(),
          from_code: t.from_code,
          to_code: t.to_code,
          allowed_roles: t.allowed_roles ?? [],
        })),
      );
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(entityType);
  }, [entityType, load]);

  // 允许角色选项 = 角色（内置+自定义） + 用户组（group:组码）
  useEffect(() => {
    void Promise.all([
      api.getList<RoleDef>('/admin/roles').catch(() => ({ items: [] as RoleDef[], total: 0 })),
      api.getList<UserGroup>('/admin/groups').catch(() => ({ items: [] as UserGroup[], total: 0 })),
    ]).then(([roles, groups]) => {
      setRoleOptions([
        ...roles.items.map((r) => ({ value: r.code, label: r.name })),
        ...groups.items.map((g) => ({ value: `group:${g.code}`, label: `${t('admin.workflow.groupPrefix')}${g.name}` })),
      ]);
    });
  }, []);

  const updateStatus = (key: string, patch: Partial<StatusRow>) => {
    setStatuses((prev) =>
      prev.map((r) => (r._key === key ? { ...r, ...patch } : r)),
    );
  };

  const setInitial = (key: string) => {
    setStatuses((prev) =>
      prev.map((r) => ({ ...r, is_initial: r._key === key })),
    );
  };

  const updateTransition = (key: string, patch: Partial<TransitionRow>) => {
    setTransitions((prev) =>
      prev.map((r) => (r._key === key ? { ...r, ...patch } : r)),
    );
  };

  const statusOptions = useMemo(
    () =>
      statuses
        .filter((s) => s.code)
        .map((s) => ({ value: s.code, label: s.name ? `${s.name}（${s.code}）` : s.code })),
    [statuses],
  );

  const handleSave = async () => {
    if (statuses.some((s) => !s.code.trim() || !s.name.trim())) {
      message.error(t('admin.workflow.statusEmptyError'));
      return;
    }
    if (transitions.some((tr) => !tr.from_code || !tr.to_code)) {
      message.error(t('admin.workflow.transitionEmptyError'));
      return;
    }
    setSaving(true);
    try {
      await api.put('/admin/workflow-config', {
        entity_type: entityType,
        statuses: statuses.map((s) => ({
          code: s.code.trim(),
          name: s.name.trim(),
          is_initial: s.is_initial,
          is_terminal: s.is_terminal,
          sort: s.sort,
        })),
        transitions: transitions.map((t) => ({
          from_code: t.from_code,
          to_code: t.to_code,
          allowed_roles: t.allowed_roles,
        })),
      });
      message.success(t('admin.workflow.saved'));
      void load(entityType);
    } catch {
      // 后端校验失败的中文错误已由拦截器统一 message.error
    } finally {
      setSaving(false);
    }
  };

  const statusColumns: ColumnsType<StatusRow> = [
    {
      title: t('admin.common.codeShort'),
      dataIndex: 'code',
      width: 180,
      render: (_, record) => (
        <Input
          value={record.code}
          maxLength={32}
          placeholder={t('admin.workflow.codePlaceholder')}
          onChange={(e) => updateStatus(record._key, { code: e.target.value })}
        />
      ),
    },
    {
      title: t('admin.common.name'),
      dataIndex: 'name',
      width: 180,
      render: (_, record) => (
        <Input
          value={record.name}
          maxLength={50}
          placeholder={t('admin.workflow.namePlaceholder')}
          onChange={(e) => updateStatus(record._key, { name: e.target.value })}
        />
      ),
    },
    {
      title: t('admin.workflow.initial'),
      dataIndex: 'is_initial',
      width: 90,
      align: 'center',
      render: (_, record) => (
        <Radio
          checked={record.is_initial}
          onChange={() => setInitial(record._key)}
        />
      ),
    },
    {
      title: t('admin.workflow.terminal'),
      dataIndex: 'is_terminal',
      width: 90,
      align: 'center',
      render: (_, record) => (
        <Switch
          checked={record.is_terminal}
          onChange={(checked) => updateStatus(record._key, { is_terminal: checked })}
        />
      ),
    },
    {
      title: t('admin.common.sort'),
      dataIndex: 'sort',
      width: 110,
      render: (_, record) => (
        <InputNumber
          value={record.sort}
          min={0}
          onChange={(v) => updateStatus(record._key, { sort: v ?? 0 })}
        />
      ),
    },
    {
      title: t('common.actions'),
      key: 'action',
      width: 80,
      render: (_, record) => (
        <Popconfirm
          title={t('admin.workflow.deleteStatus')}
          onConfirm={() =>
            setStatuses((prev) => prev.filter((r) => r._key !== record._key))
          }
        >
          <Button type="link" size="small" danger>
            {t('common.delete')}
          </Button>
        </Popconfirm>
      ),
    },
  ];

  const transitionColumns: ColumnsType<TransitionRow> = [
    {
      title: t('admin.workflow.fromStatus'),
      dataIndex: 'from_code',
      width: 200,
      render: (_, record) => (
        <Select
          style={{ width: '100%' }}
          value={record.from_code || undefined}
          placeholder={t('admin.workflow.selectStatus')}
          options={statusOptions}
          onChange={(v) => updateTransition(record._key, { from_code: v })}
        />
      ),
    },
    {
      title: t('admin.workflow.toStatus'),
      dataIndex: 'to_code',
      width: 200,
      render: (_, record) => (
        <Select
          style={{ width: '100%' }}
          value={record.to_code || undefined}
          placeholder={t('admin.workflow.selectStatus')}
          options={statusOptions}
          onChange={(v) => updateTransition(record._key, { to_code: v })}
        />
      ),
    },
    {
      title: t('admin.workflow.allowedRoles'),
      dataIndex: 'allowed_roles',
      render: (_, record) => (
        <Select
          mode="multiple"
          style={{ width: '100%' }}
          value={record.allowed_roles}
          placeholder={t('admin.workflow.anyRole')}
          optionFilterProp="label"
          options={roleOptions}
          onChange={(v) => updateTransition(record._key, { allowed_roles: v })}
        />
      ),
    },
    {
      title: t('common.actions'),
      key: 'action',
      width: 80,
      render: (_, record) => (
        <Popconfirm
          title={t('admin.workflow.deleteTransition')}
          onConfirm={() =>
            setTransitions((prev) => prev.filter((r) => r._key !== record._key))
          }
        >
          <Button type="link" size="small" danger>
            {t('common.delete')}
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <Card
      title={t('admin.workflow.title')}
      extra={
        <Space>
          <Segmented<WorkflowEntityType>
            value={entityType}
            onChange={(v) => setEntityType(v)}
            options={(
              Object.keys(WORKFLOW_ENTITY_LABELS) as WorkflowEntityType[]
            ).map((k) => ({ value: k, label: et.workflowEntity(k) }))}
          />
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
            onClick={() => void handleSave()}
          >
            {t('common.save')}
          </Button>
        </Space>
      }
    >
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message={t('admin.workflow.alert')}
      />

      <Typography.Title level={5}>{t('admin.workflow.statusDef')}</Typography.Title>
      <Table<StatusRow>
        rowKey="_key"
        size="small"
        loading={loading}
        columns={statusColumns}
        dataSource={statuses}
        standardToolbar={{ exportFileName: '流程状态定义', searchPlaceholder: '搜索状态编码或名称' }}
        pagination={false}
      />
      <Button
        type="dashed"
        block
        icon={<PlusOutlined />}
        style={{ marginTop: 8 }}
        onClick={() =>
          setStatuses((prev) => [
            ...prev,
            {
              _key: nextKey(),
              code: '',
              name: '',
              is_initial: prev.length === 0,
              is_terminal: false,
              sort: prev.length > 0 ? Math.max(...prev.map((s) => s.sort)) + 1 : 1,
            },
          ])
        }
      >
        {t('admin.workflow.addStatus')}
      </Button>

      <Divider />

      <Typography.Title level={5}>{t('admin.workflow.transitionRules')}</Typography.Title>
      <Table<TransitionRow>
        rowKey="_key"
        size="small"
        loading={loading}
        columns={transitionColumns}
        dataSource={transitions}
        standardToolbar={{ exportFileName: '流程流转规则', searchPlaceholder: '搜索来源状态、目标状态或角色' }}
        pagination={false}
      />
      <Button
        type="dashed"
        block
        icon={<PlusOutlined />}
        style={{ marginTop: 8 }}
        onClick={() =>
          setTransitions((prev) => [
            ...prev,
            { _key: nextKey(), from_code: '', to_code: '', allowed_roles: [] },
          ])
        }
      >
        {t('admin.workflow.addTransition')}
      </Button>
    </Card>
  );
}
