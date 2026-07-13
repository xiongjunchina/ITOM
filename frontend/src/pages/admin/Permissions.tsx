import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Empty,
  Flex,
  Modal,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { SaveOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import type { PermAction, PermissionModule, RoleDef, RolePermissionEntry } from '../../api/types';
import { translate, useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';
import { useLangStore } from '../../i18n/store';

interface ModulesResp {
  actions: string[];
  modules: PermissionModule[];
}

/** 矩阵：模块码 → 已勾选动作集合 */
type Matrix = Record<string, string[]>;

/** 归一化（模块排序 + 动作按注册顺序排序 + 去掉空行）用于脏检查 */
function normalize(matrix: Matrix, actionOrder: string[]): string {
  const entries = Object.entries(matrix)
    .map(([m, acts]) => [m, actionOrder.filter((a) => acts.includes(a))] as const)
    .filter(([, acts]) => acts.length > 0)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return JSON.stringify(entries);
}

/** 表格行：分组标题行 / 菜单页小标题行 / 模块行 */
interface GridRow {
  key: string;
  groupHeader?: string;
  pageHeader?: string; // 菜单页中文名
  module?: PermissionModule;
  indented?: boolean; // 该模块归属某菜单页，缩进展示
}

export default function Permissions() {
  const t = useT();
  const et = useEnums();
  const lang = useLangStore((s) => s.lang);
  const [roles, setRoles] = useState<RoleDef[]>([]);
  const [modules, setModules] = useState<PermissionModule[]>([]);
  const [actions, setActions] = useState<string[]>(['view', 'create', 'edit', 'delete']);
  const [metaLoading, setMetaLoading] = useState(true);

  // 优先用 dict 翻译（与左侧导航/后端 MODULES 一致）；无对应键时回退后端 name/分组名
  const moduleLabel = (m: PermissionModule) => {
    const key = 'module.' + m.code;
    const v = translate(lang, key);
    return v === key ? m.name : v;
  };
  const groupLabel = (g: string) => {
    const key = 'group.' + g;
    const v = translate(lang, key);
    return v === key ? g : v;
  };
  // 菜单页小标题：优先 i18n（permPage.<code>），回退后端 page_name
  const pageLabel = (m: PermissionModule) => {
    if (!m.page) return '';
    const key = 'permPage.' + m.page;
    const v = translate(lang, key);
    return v === key ? m.page_name || m.page : v;
  };

  const [selected, setSelected] = useState<string>(''); // 角色 code
  const [matrix, setMatrix] = useState<Matrix>({});
  const [savedSnapshot, setSavedSnapshot] = useState<string>('');
  const [gridLoading, setGridLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const isAdmin = selected === 'admin';
  const dirty = !isAdmin && !!selected && normalize(matrix, actions) !== savedSnapshot;

  const loadMatrix = useCallback(
    async (roleCode: string) => {
      setSelected(roleCode);
      if (roleCode === 'admin') {
        // admin 隐式全权：不从后端取，网格只读全勾
        setMatrix({});
        setSavedSnapshot('');
        return;
      }
      setGridLoading(true);
      // 先清空，避免加载期间残留上一角色的矩阵（及误判"未保存"）
      setMatrix({});
      setSavedSnapshot(normalize({}, actions));
      try {
        const entries = await api.get<RolePermissionEntry[]>('/admin/permissions', { role: roleCode });
        const m: Matrix = {};
        (entries ?? []).forEach((e) => {
          m[e.module] = e.actions ?? [];
        });
        setMatrix(m);
        setSavedSnapshot(normalize(m, actions));
      } catch {
        // 已统一提示
      } finally {
        setGridLoading(false);
      }
    },
    [actions],
  );

  useEffect(() => {
    (async () => {
      setMetaLoading(true);
      try {
        const [roleRes, moduleRes] = await Promise.all([
          api.getList<RoleDef>('/admin/roles'),
          api.get<ModulesResp>('/admin/permission-modules'),
        ]);
        setRoles(roleRes.items);
        setModules(moduleRes.modules ?? []);
        if (moduleRes.actions?.length) setActions(moduleRes.actions);
        const first = roleRes.items.find((r) => r.code !== 'admin');
        if (first) void loadMatrix(first.code);
      } catch {
        // 已统一提示
      } finally {
        setMetaLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** 切换角色（未保存时 Modal 提醒） */
  const handleSelect = (roleCode: string) => {
    if (roleCode === selected) return;
    if (dirty) {
      Modal.confirm({
        title: t('admin.permissions.unsavedTitle'),
        content: t('admin.permissions.unsavedContent'),
        okText: t('admin.permissions.discardSwitch'),
        cancelText: t('admin.permissions.stay'),
        onOk: () => void loadMatrix(roleCode),
      });
      return;
    }
    void loadMatrix(roleCode);
  };

  const toggleAction = (moduleCode: string, action: string, checked: boolean) => {
    setMatrix((prev) => {
      const cur = new Set(prev[moduleCode] ?? []);
      if (checked) cur.add(action);
      else cur.delete(action);
      return { ...prev, [moduleCode]: Array.from(cur) };
    });
  };

  const toggleAll = (moduleCode: string, checked: boolean) => {
    setMatrix((prev) => ({ ...prev, [moduleCode]: checked ? [...actions] : [] }));
  };

  const handleSave = async () => {
    if (!selected || isAdmin) return;
    setSaving(true);
    try {
      await api.put('/admin/permissions', {
        role_code: selected,
        entries: modules.map((m) => ({ module: m.code, actions: matrix[m.code] ?? [] })),
      });
      message.success(t('admin.permissions.saved'));
      setSavedSnapshot(normalize(matrix, actions));
    } catch {
      // 已统一提示（如 ADMIN_LOCKED）
    } finally {
      setSaving(false);
    }
  };

  /** 分组标题行 + 菜单页小标题 + 模块行（保持后端注册顺序，按菜单页分层） */
  const rows = useMemo<GridRow[]>(() => {
    const out: GridRow[] = [];
    let lastGroup = '';
    let lastPage = '';
    modules.forEach((m) => {
      if (m.group !== lastGroup) {
        lastGroup = m.group;
        lastPage = '';
        out.push({ key: `__group_${m.group}`, groupHeader: m.group });
      }
      if (m.page) {
        if (m.page !== lastPage) {
          lastPage = m.page;
          out.push({ key: `__page_${m.page}`, pageHeader: pageLabel(m) });
        }
      } else {
        lastPage = '';
      }
      out.push({ key: m.code, module: m, indented: !!m.page });
    });
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modules, lang]);

  const columnCount = actions.length + 2;

  const columns: ColumnsType<GridRow> = useMemo(() => {
    const cols: ColumnsType<GridRow> = [
      {
        title: t('admin.permissions.colModule'),
        key: 'name',
        width: 240,
        onCell: (row) => (row.groupHeader || row.pageHeader ? { colSpan: columnCount } : {}),
        render: (_, row) =>
          row.groupHeader ? (
            <Typography.Text strong>{groupLabel(row.groupHeader)}</Typography.Text>
          ) : row.pageHeader ? (
            <Typography.Text type="secondary" style={{ paddingLeft: 16, fontWeight: 500 }}>
              {row.pageHeader}
            </Typography.Text>
          ) : row.module ? (
            <span style={{ paddingLeft: row.indented ? 32 : 0 }}>{moduleLabel(row.module)}</span>
          ) : null,
      },
      {
        title: t('admin.permissions.colAll'),
        key: 'all',
        width: 80,
        align: 'center',
        onCell: (row) => (row.groupHeader || row.pageHeader ? { colSpan: 0 } : {}),
        render: (_, row) => {
          if (!row.module) return null;
          const acts = isAdmin ? actions : matrix[row.module.code] ?? [];
          const checkedCount = actions.filter((a) => acts.includes(a)).length;
          return (
            <Checkbox
              disabled={isAdmin}
              checked={checkedCount === actions.length}
              indeterminate={checkedCount > 0 && checkedCount < actions.length}
              onChange={(e) => toggleAll(row.module!.code, e.target.checked)}
            />
          );
        },
      },
      ...actions.map<ColumnsType<GridRow>[number]>((action) => ({
        title: et.permAction(action as PermAction) || action,
        key: action,
        width: 80,
        align: 'center',
        onCell: (row) => (row.groupHeader || row.pageHeader ? { colSpan: 0 } : {}),
        render: (_, row) => {
          if (!row.module) return null;
          const checked = isAdmin || (matrix[row.module.code] ?? []).includes(action);
          return (
            <Checkbox
              disabled={isAdmin}
              checked={checked}
              onChange={(e) => toggleAction(row.module!.code, action, e.target.checked)}
            />
          );
        },
      })),
    ];
    return cols;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [actions, matrix, isAdmin, columnCount, lang]);

  const selectedRole = roles.find((r) => r.code === selected);

  return (
    <Card title={t('admin.permissions.title')}>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={t('admin.permissions.alert')}
      />
      <Flex gap={16} align="flex-start">
        <Card size="small" title={t('admin.permissions.rolesTitle')} style={{ width: 260, flexShrink: 0 }} styles={{ body: { padding: 8 } }}>
          <Spin spinning={metaLoading}>
            <div>
              {roles.map((r) => {
                const admin = r.code === 'admin';
                const active = r.code === selected;
                return (
                  <div
                    key={r.code}
                    onClick={() => handleSelect(r.code)}
                    style={{
                      padding: '8px 12px',
                      borderRadius: 6,
                      cursor: 'pointer',
                      marginBottom: 2,
                      background: active ? '#e6f4ff' : undefined,
                      opacity: admin ? 0.55 : 1,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 8,
                    }}
                  >
                    <Typography.Text
                      style={{ color: active ? '#1677ff' : undefined }}
                      ellipsis={{ tooltip: r.name }}
                    >
                      {r.name}
                    </Typography.Text>
                    <Space size={4} style={{ flexShrink: 0 }}>
                      {admin ? (
                        <Tag>{t('admin.permissions.implicitAll')}</Tag>
                      ) : r.is_builtin ? (
                        <Tag color="blue">{t('admin.roles.builtin')}</Tag>
                      ) : (
                        <Tag color="green">{t('admin.roles.custom')}</Tag>
                      )}
                    </Space>
                  </div>
                );
              })}
              {!metaLoading && roles.length === 0 && (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t('admin.permissions.noRoles')} />
              )}
            </div>
          </Spin>
        </Card>

        <Card
          size="small"
          style={{ flex: 1, minWidth: 0 }}
          title={
            selectedRole ? (
              <Space>
                <span>{selectedRole.name}</span>
                <Typography.Text type="secondary" style={{ fontWeight: 'normal' }}>
                  {selectedRole.code}
                </Typography.Text>
                {dirty && <Tag color="orange">{t('admin.permissions.unsaved')}</Tag>}
              </Space>
            ) : (
              t('admin.permissions.matrixTitle')
            )
          }
          extra={
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saving}
              disabled={isAdmin || !selected || !dirty}
              onClick={() => void handleSave()}
            >
              {t('common.save')}
            </Button>
          }
        >
          {isAdmin && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message={t('admin.permissions.adminAlert')}
            />
          )}
          {selected ? (
            <Table<GridRow>
              rowKey="key"
              size="small"
              loading={gridLoading}
              columns={columns}
              dataSource={rows}
              pagination={false}
            />
          ) : (
            <Empty description={t('admin.permissions.selectRole')} />
          )}
        </Card>
      </Flex>
    </Card>
  );
}
