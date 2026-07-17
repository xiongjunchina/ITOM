import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Card,
  Collapse,
  Divider,
  Input,
  InputNumber,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import { ReloadOutlined, SaveOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { useT } from '../../i18n';
import { useAuthStore } from '../../stores/auth';
import { useRoleOptions } from '../../utils/roleOptions';
import type { Member, ReviewAssignees, ScoringConfig, ScoringDimKey } from '../../api/types';
import { DIMENSIONS } from '../requirements/dimensions';

type Weights = Record<ScoringDimKey, number>;
type Thresholds = { total: number; strategic: number; viable: number };
type Rubric = Record<string, { name: string; '5': string; '4': string; '3': string; '2': string; '1': string }>;

const LEVELS: ('5' | '4' | '3' | '2' | '1')[] = ['5', '4', '3', '2', '1'];

export default function RequirementScoring({ embedded }: { embedded?: boolean }) {
  const t = useT();
  const { roleLabel } = useRoleOptions();
  const user = useAuthStore((s) => s.user);
  const isAdmin = !!user?.permissions?.['*'] || !!user?.roles?.includes('admin');

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [defaults, setDefaults] = useState<ScoringConfig['defaults'] | null>(null);

  const [weights, setWeights] = useState<Weights>({ d1: 0, d2: 0, d3: 0, d4: 0, d5: 0, d6: 0 });
  const [thresholds, setThresholds] = useState<Thresholds>({ total: 0, strategic: 0, viable: 0 });
  const [rubric, setRubric] = useState<Rubric>({});
  const [roleWeights, setRoleWeights] = useState<Record<string, number>>({});
  // M16 分流规则：转项目人天阈值 + 方案评估指派
  const [effortThreshold, setEffortThreshold] = useState<number>(20);
  const [reviewAssignees, setReviewAssignees] = useState<ReviewAssignees>({});
  const [members, setMembers] = useState<Member[]>([]);

  const apply = useCallback(
    (
      c: Pick<ScoringConfig, 'weights' | 'thresholds' | 'rubric' | 'role_weights'> & {
        effort_threshold?: number;
        review_assignees?: ReviewAssignees;
      },
    ) => {
      setWeights({ ...c.weights });
      setThresholds({ ...c.thresholds });
      setRubric(JSON.parse(JSON.stringify(c.rubric)) as Rubric);
      setRoleWeights({ ...(c.role_weights ?? {}) });
      // 恢复默认仅回填阈值（defaults 不含指派人，保持现值）
      if (c.effort_threshold != null) setEffortThreshold(c.effort_threshold);
      if (c.review_assignees) setReviewAssignees({ ...c.review_assignees });
    },
    [],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const c = await api.get<ScoringConfig>('/requirements/scoring-config');
      apply(c);
      setDefaults(c.defaults ?? null);
    } catch {
      // 已统一提示
    } finally {
      setLoading(false);
    }
  }, [apply]);

  useEffect(() => {
    void load();
  }, [load]);

  // 方案评估指派人员下拉（只读用户也需名字回显）
  useEffect(() => {
    api
      .getList<Member>('/members', { page: 1, page_size: 2000 })
      .then((res) => setMembers(res.items))
      .catch(() => undefined);
  }, []);

  const memberOptions = useMemo(
    () =>
      members.map((m) => ({
        value: m.id,
        label: m.department_name ? `${m.name}（${m.department_name}）` : m.name,
      })),
    [members],
  );

  const weightsSum = Math.round(DIMENSIONS.reduce((acc, d) => acc + (weights[d.short] ?? 0), 0) * 100) / 100;
  const weightsValid = Math.abs(weightsSum - 1) < 1e-9;

  const handleSave = async () => {
    if (!weightsValid) {
      message.error(t('req.cfg.weightsSumError', { sum: weightsSum }));
      return;
    }
    setSaving(true);
    try {
      await api.put('/requirements/scoring-config', {
        weights,
        thresholds,
        rubric,
        role_weights: roleWeights,
        effort_threshold: effortThreshold,
        review_assignees: reviewAssignees,
      });
      message.success(t('req.cfg.saved'));
      void load();
    } catch {
      // 后端 INVALID_WEIGHTS / INVALID_THRESHOLD 等中文错误已由拦截器统一提示
    } finally {
      setSaving(false);
    }
  };

  const restoreDefault = () => {
    if (defaults) apply(defaults);
  };

  if (loading) {
    const spin = (
      <div style={{ textAlign: 'center', padding: 60 }}>
        <Spin size="large" />
      </div>
    );
    return embedded ? spin : <Card title={t('req.cfg.title')}>{spin}</Card>;
  }

  const disabled = !isAdmin;
  const roleWeightKeys = Object.keys(roleWeights);

  const toolbar = isAdmin ? (
    <Space>
      <Button icon={<ReloadOutlined />} disabled={!defaults} onClick={restoreDefault}>
        {t('req.cfg.restoreDefault')}
      </Button>
      <Button
        type="primary"
        icon={<SaveOutlined />}
        loading={saving}
        disabled={!weightsValid}
        onClick={() => void handleSave()}
      >
        {t('common.save')}
      </Button>
    </Space>
  ) : null;
  const body = (
    <>
      {!isAdmin && <Alert type="info" showIcon style={{ marginBottom: 16 }} message={t('req.cfg.readonly')} />}

      {/* 六维权重 */}
      <Typography.Title level={5}>{t('req.cfg.weights')}</Typography.Title>
      <Space wrap size={16}>
        {DIMENSIONS.map((d) => (
          <div key={d.short} style={{ display: 'flex', flexDirection: 'column' }}>
            <Typography.Text>
              {d.code} · {t(d.nameKey)}
              {d.reverse && (
                <Tag color="orange" style={{ marginInlineStart: 4 }}>
                  {t('req.cfg.reverseTag')}
                </Tag>
              )}
            </Typography.Text>
            <InputNumber
              min={0}
              max={1}
              step={0.05}
              disabled={disabled}
              style={{ width: 120 }}
              value={weights[d.short]}
              onChange={(v) => setWeights((w) => ({ ...w, [d.short]: v ?? 0 }))}
            />
          </div>
        ))}
      </Space>
      <div style={{ marginTop: 12 }}>
        {weightsValid ? (
          <Tag color="green">{t('req.cfg.weightsSum', { sum: weightsSum })}</Tag>
        ) : (
          <Alert type="error" showIcon message={t('req.cfg.weightsSumError', { sum: weightsSum })} />
        )}
      </div>

      <Divider />

      {/* 四象限阈值 */}
      <Typography.Title level={5}>{t('req.cfg.thresholds')}</Typography.Title>
      <Space wrap size={16}>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <Typography.Text>{t('req.cfg.thrTotal')}</Typography.Text>
          <InputNumber
            min={0}
            step={0.1}
            disabled={disabled}
            style={{ width: 160 }}
            value={thresholds.total}
            onChange={(v) => setThresholds((s) => ({ ...s, total: v ?? 0 }))}
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <Typography.Text>{t('req.cfg.thrStrategic')}</Typography.Text>
          <InputNumber
            min={0}
            step={0.1}
            disabled={disabled}
            style={{ width: 160 }}
            value={thresholds.strategic}
            onChange={(v) => setThresholds((s) => ({ ...s, strategic: v ?? 0 }))}
          />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <Typography.Text>{t('req.cfg.thrViable')}</Typography.Text>
          <InputNumber
            min={0}
            step={0.1}
            disabled={disabled}
            style={{ width: 160 }}
            value={thresholds.viable}
            onChange={(v) => setThresholds((s) => ({ ...s, viable: v ?? 0 }))}
          />
        </div>
      </Space>

      <Divider />

      {/* M16 分流规则：转项目人天阈值 + 方案评估指派 */}
      <Typography.Title level={5}>{t('req.cfg.routing')}</Typography.Title>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <Typography.Text>{t('req.cfg.effortThreshold')}</Typography.Text>
          <InputNumber
            min={1}
            step={1}
            disabled={disabled}
            style={{ width: 160 }}
            value={effortThreshold}
            onChange={(v) => setEffortThreshold(v ?? 1)}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12, marginTop: 4 }}>
            {t('req.cfg.effortThresholdHint')}
          </Typography.Text>
        </div>
        <div>
          <Typography.Text strong>{t('req.cfg.reviewAssignees')}</Typography.Text>
          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {t('req.cfg.reviewAssigneesHint')}
            </Typography.Text>
          </div>
          <Space wrap size={16} style={{ marginTop: 8 }}>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <Typography.Text>{t('req.cfg.pdmLeader')}</Typography.Text>
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                disabled={disabled}
                style={{ width: 220 }}
                placeholder={t('req.selectMember')}
                value={reviewAssignees.pdm_leader ?? undefined}
                onChange={(v) => setReviewAssignees((a) => ({ ...a, pdm_leader: v ?? null }))}
                options={memberOptions}
              />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <Typography.Text>{t('req.cfg.devLeader')}</Typography.Text>
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                disabled={disabled}
                style={{ width: 220 }}
                placeholder={t('req.selectMember')}
                value={reviewAssignees.dev_leader ?? undefined}
                onChange={(v) => setReviewAssignees((a) => ({ ...a, dev_leader: v ?? null }))}
                options={memberOptions}
              />
            </div>
          </Space>
        </div>
      </Space>

      <Divider />

      {/* 六维 1-5 分档说明 */}
      <Typography.Title level={5}>{t('req.cfg.rubric')}</Typography.Title>
      <Collapse
        items={DIMENSIONS.map((d) => {
          const r = rubric[d.short];
          return {
            key: d.short,
            label: (
              <span>
                {d.code} · {t(d.nameKey)}
                {r?.name ? `（${r.name}）` : ''}
              </span>
            ),
            children: r ? (
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <Input
                  addonBefore={t('req.cfg.dimName')}
                  disabled={disabled}
                  value={r.name}
                  maxLength={50}
                  onChange={(e) =>
                    setRubric((prev) => ({ ...prev, [d.short]: { ...prev[d.short], name: e.target.value } }))
                  }
                />
                {LEVELS.map((lv) => (
                  <div key={lv} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                    <Tag style={{ marginTop: 4, minWidth: 48, textAlign: 'center' }}>
                      {t('req.cfg.levelN', { n: lv })}
                    </Tag>
                    <Input.TextArea
                      autoSize={{ minRows: 1 }}
                      disabled={disabled}
                      style={{ flex: 1 }}
                      value={r[lv]}
                      maxLength={200}
                      onChange={(e) =>
                        setRubric((prev) => ({ ...prev, [d.short]: { ...prev[d.short], [lv]: e.target.value } }))
                      }
                    />
                  </div>
                ))}
              </Space>
            ) : null,
          };
        })}
      />

      {/* 评审角色权重（可选，仅当后端返回时展示） */}
      {roleWeightKeys.length > 0 && (
        <>
          <Divider />
          <Typography.Title level={5}>{t('req.cfg.roleWeights')}</Typography.Title>
          <Space wrap size={16}>
            {roleWeightKeys.map((code) => (
              <div key={code} style={{ display: 'flex', flexDirection: 'column' }}>
                <Typography.Text>{roleLabel(code)}</Typography.Text>
                <InputNumber
                  min={0}
                  step={0.1}
                  disabled={disabled}
                  style={{ width: 140 }}
                  value={roleWeights[code]}
                  onChange={(v) => setRoleWeights((rw) => ({ ...rw, [code]: v ?? 0 }))}
                />
              </div>
            ))}
          </Space>
        </>
      )}
    </>
  );
  return embedded ? (
    <div>
      {toolbar && <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>{toolbar}</div>}
      {body}
    </div>
  ) : (
    <Card title={t('req.cfg.title')} extra={toolbar}>
      {body}
    </Card>
  );
}
