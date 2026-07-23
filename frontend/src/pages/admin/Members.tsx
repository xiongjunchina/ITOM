import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Tag,
  TreeSelect,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import Table from '../../components/SortableTable';
import { PlusOutlined } from '@ant-design/icons';
import dayjs, { Dayjs } from 'dayjs';
import { api } from '../../api/client';
import type { Department, Member, Position } from '../../api/types';
import { buildDeptTreeSelectData } from '../../utils/dept';
import { useT } from '../../i18n';
import { useEnums } from '../../i18n/enums';

interface MemberForm {
  name: string;
  name_en?: string;
  department_id?: string | null;
  position_id?: string | null;
  status?: '在岗' | '离职';
  hire_date?: Dayjs | null;
  email?: string;
  mobile?: string;
  skills?: string[];
  remarks?: string;
}

export default function Members() {
  const t = useT();
  const et = useEnums();
  const [items, setItems] = useState<Member[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(false);
  const [positions, setPositions] = useState<Position[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Member | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<MemberForm>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.getList<Member>('/members', {
        page,
        page_size: pageSize,
        q: q || undefined,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, q]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    api
      .getList<Position>('/positions', { page: 1, page_size: 999 })
      .then((res) => setPositions(res.items))
      .catch(() => undefined);
    api
      .getList<Department>('/admin/departments')
      .then((res) => setDepartments(res.items))
      .catch(() => undefined);
  }, []);

  const deptTreeData = useMemo(() => buildDeptTreeSelectData(departments), [departments]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setModalOpen(true);
  };

  const openEdit = (record: Member) => {
    setEditing(record);
    form.setFieldsValue({
      name: record.name,
      name_en: record.name_en ?? undefined,
      department_id: record.department_id ?? undefined,
      position_id: record.position_id ?? undefined,
      status: record.status ?? undefined,
      hire_date: record.hire_date ? dayjs(record.hire_date) : undefined,
      email: record.email ?? undefined,
      mobile: record.mobile ?? undefined,
      skills: record.skills ?? undefined,
      remarks: record.remarks ?? undefined,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    const values = await form.validateFields();
    const payload = {
      name: values.name,
      name_en: values.name_en ?? null,
      department_id: values.department_id ?? null,
      position_id: values.position_id ?? null,
      status: values.status,
      hire_date: values.hire_date ? values.hire_date.format('YYYY-MM-DD') : null,
      email: values.email ?? null,
      mobile: values.mobile ?? null,
      skills: values.skills ?? [],
      remarks: values.remarks ?? null,
    };
    setSaving(true);
    try {
      if (editing) {
        await api.patch(`/members/${editing.id}`, payload);
        message.success(t('admin.member.updated'));
      } else {
        await api.post('/members', payload);
        message.success(t('admin.member.created'));
      }
      setModalOpen(false);
      void load();
    } catch {
      // 已统一提示
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<Member> = [
    { title: t('admin.member.name'), dataIndex: 'name', width: 100, fixed: 'left' },
    {
      title: t('admin.member.nameEn'),
      dataIndex: 'name_en',
      width: 110,
      render: (v: string | null | undefined) => v || '-',
    },
    {
      title: t('admin.member.dept'),
      dataIndex: 'department_name',
      width: 140,
      render: (v: string | null | undefined) => v || '-',
    },
    {
      title: t('admin.member.position'),
      dataIndex: 'position_name',
      width: 120,
      render: (v: string | null | undefined) => v || '-',
    },
    {
      title: t('common.status'),
      dataIndex: 'status',
      width: 80,
      render: (v: Member['status']) =>
        v ? <Tag color={v === '在岗' ? 'green' : 'default'}>{et.memberStatus(v)}</Tag> : '-',
    },
    { title: t('admin.member.hireDate'), dataIndex: 'hire_date', width: 110, onCell: () => ({ className: 'cell-nowrap' }) },
    {
      title: t('admin.member.email'),
      dataIndex: 'email',
      width: 180,
      ellipsis: true,
      render: (v: string | null | undefined) => v || '-',
    },
    {
      title: t('admin.member.mobile'),
      dataIndex: 'mobile',
      width: 130,
      onCell: () => ({ className: 'cell-nowrap' }),
      render: (v: string | null | undefined) => v || '-',
    },
    {
      title: t('admin.member.skills'),
      dataIndex: 'skills',
      width: 160,
      render: (skills: string[] | null) =>
        (skills ?? []).length === 0 ? (
          '-'
        ) : (
          <>
            {(skills ?? []).map((s) => (
              <Tag key={s}>{s}</Tag>
            ))}
          </>
        ),
    },
    {
      title: t('admin.common.syncSource'),
      dataIndex: 'external_source',
      width: 100,
      render: (v: string | null | undefined) => v || '-',
    },
    {
      title: t('common.actions'),
      key: 'action',
      width: 80,
      fixed: 'right',
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => openEdit(record)}>
          {t('common.edit')}
        </Button>
      ),
    },
  ];

  return (
    <Card
      title={t('admin.member.title')}
      extra={
        <Space>
          <Input.Search
            placeholder={t('admin.member.searchPlaceholder')}
            allowClear
            onSearch={(v) => {
              setPage(1);
              setQ(v);
            }}
            style={{ width: 220 }}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            {t('admin.member.new')}
          </Button>
        </Space>
      }
    >
      <Table<Member>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        standardToolbar={{ exportFileName: '人员主数据', showSearch: false, showFilter: false }}
        sticky
        scroll={{ x: 'max-content' }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (n) => t('admin.total', { n }),
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />

      <Modal
        title={editing ? t('admin.member.edit') : t('admin.member.new')}
        open={modalOpen}
        onOk={() => void handleSave()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
        width={560}
      >
        <Form<MemberForm>
          form={form}
          layout="vertical"
          preserve={false}
          initialValues={{ status: '在岗' }}
        >
          <Space.Compact block>
            <Form.Item
              name="name"
              label={t('admin.member.nameCn')}
              style={{ width: '50%', marginRight: 8 }}
              rules={[{ required: true, message: t('admin.member.nameCnRequired') }]}
            >
              <Input maxLength={50} />
            </Form.Item>
            <Form.Item name="name_en" label={t('admin.member.nameEnCn')} style={{ width: '50%' }}>
              <Input maxLength={50} placeholder={t('admin.member.nameEnPlaceholder')} />
            </Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item name="department_id" label={t('admin.member.dept')} style={{ width: '50%', marginRight: 8 }}>
              <TreeSelect
                allowClear
                showSearch
                treeDefaultExpandAll
                treeNodeFilterProp="title"
                placeholder={t('admin.member.selectDeptTree')}
                treeData={deptTreeData}
              />
            </Form.Item>
            <Form.Item name="position_id" label={t('admin.member.position')} style={{ width: '50%' }}>
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder={t('admin.member.selectPosition')}
                options={positions.map((p) => ({ value: p.id, label: p.name }))}
              />
            </Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item name="status" label={t('common.status')} style={{ width: '50%', marginRight: 8 }}>
              <Select
                options={[
                  { value: '在岗', label: et.memberStatus('在岗') },
                  { value: '离职', label: et.memberStatus('离职') },
                ]}
              />
            </Form.Item>
            <Form.Item name="hire_date" label={t('admin.member.hireDate')} style={{ width: '50%' }}>
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
          </Space.Compact>
          <Space.Compact block>
            <Form.Item
              name="email"
              label={t('admin.member.email')}
              style={{ width: '50%', marginRight: 8 }}
              rules={[{ type: 'email', message: t('admin.member.emailInvalid') }]}
            >
              <Input maxLength={100} />
            </Form.Item>
            <Form.Item name="mobile" label={t('admin.member.mobile')} style={{ width: '50%' }}>
              <Input maxLength={20} />
            </Form.Item>
          </Space.Compact>
          <Form.Item name="skills" label={t('admin.member.skillsTag')}>
            <Select mode="tags" placeholder={t('admin.member.skillsPlaceholder')} open={false} suffixIcon={null} />
          </Form.Item>
          <Form.Item name="remarks" label={t('common.remark')}>
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
