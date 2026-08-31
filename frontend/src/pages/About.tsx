import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Alert, Button, Card, Col, Descriptions, Divider, List, Row, Space, Tag, Timeline, Typography } from 'antd';
import { CodeOutlined, CustomerServiceOutlined, GlobalOutlined, HistoryOutlined, LinkOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { api } from '../api/client';
import { useLangStore } from '../i18n/store';
import { buildRelease, type PublicSoftwareRelease } from '../release';
import { localized, useBrandingStore } from '../stores/branding';

function safeExternalUrl(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.trim()) return undefined;
  const candidate = value.trim();
  if (candidate.startsWith('/')) return candidate;
  try {
    const url = new URL(candidate);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.toString() : undefined;
  } catch {
    return undefined;
  }
}

function releaseLabel(release: PublicSoftwareRelease, english: boolean): string {
  const labels = english
    ? { stable: 'Stable', candidate: 'Release candidate', development: 'Development' }
    : { stable: '正式版', candidate: '候选版', development: '开发版' };
  return labels[release.release.channel];
}

export default function About() {
  const [current, setCurrent] = useState<PublicSoftwareRelease>(buildRelease);
  const [history, setHistory] = useState<PublicSoftwareRelease[]>([buildRelease]);
  const [runtimeMismatch, setRuntimeMismatch] = useState(false);
  const lang = useLangStore((state) => state.lang);
  const english = lang === 'en';
  const branding = useBrandingStore((state) => state.current?.config);

  useEffect(() => {
    Promise.all([
      api.get<PublicSoftwareRelease>('/public/releases/current'),
      api.getList<PublicSoftwareRelease>('/public/releases'),
    ]).then(([runtime, catalog]) => {
      setCurrent(runtime);
      setHistory(catalog.items);
      setRuntimeMismatch(runtime.release.version !== buildRelease.release.version);
    }).catch(() => undefined);
  }, []);

  const notes = current.notes[lang];
  const productName = localized(branding, 'brand', 'system_name', lang, english ? current.product.name_en : current.product.name_zh);
  const edition = english ? current.product.edition_en : current.product.edition_zh;
  const developer = localized(branding, 'legal', 'developer_name', lang, english ? 'ITOM Development Team' : 'ITOM 开发团队');
  const vendor = localized(branding, 'legal', 'vendor_name', lang);
  const copyrightHolder = localized(branding, 'legal', 'copyright_holder', lang, 'ITOM');
  const licenseName = localized(branding, 'legal', 'license_name', lang, english ? 'Proprietary Software' : '专有软件');
  const website = safeExternalUrl(branding?.legal.website_url);
  const support = safeExternalUrl(branding?.legal.support_url);
  const license = safeExternalUrl(branding?.legal.license_url);
  const thirdParty = safeExternalUrl(branding?.legal.third_party_notices_url);
  const legalLinks = useMemo(() => [
    website && { key: 'website', label: english ? 'Website' : '官方网站', href: website, icon: <GlobalOutlined /> },
    support && { key: 'support', label: english ? 'Support' : '技术支持', href: support, icon: <CustomerServiceOutlined /> },
    license && { key: 'license', label: english ? 'License' : '软件许可', href: license, icon: <SafetyCertificateOutlined /> },
    thirdParty && { key: 'third-party', label: english ? 'Third-party notices' : '第三方开源声明', href: thirdParty, icon: <CodeOutlined /> },
  ].filter(Boolean) as Array<{ key: string; label: string; href: string; icon: ReactNode }>, [english, license, support, thirdParty, website]);

  return <Space direction="vertical" size={18} style={{ width: '100%' }}>
    {runtimeMismatch && <Alert showIcon type="warning" message={english ? 'Frontend and backend versions do not match' : '前端与后端版本不一致'} description={english ? 'Refresh or contact an administrator before relying on this build.' : '请刷新页面；若仍存在，请联系管理员检查部署是否完整。'} />}
    <Card className="about-release-hero">
      <Row gutter={[32, 24]} align="middle">
        <Col flex="auto">
          <Space direction="vertical" size={10}>
            <Space wrap>
              <Tag color="blue">{releaseLabel(current, english)}</Tag>
              <Typography.Text className="about-release-kicker">{english ? 'SOFTWARE RELEASE' : '软件版本'}</Typography.Text>
            </Space>
            <Typography.Title level={1}>{productName}</Typography.Title>
            <Typography.Paragraph>{notes.summary}</Typography.Paragraph>
            <Space wrap size="middle">
              <span className="about-release-version">v{current.release.version}</span>
              <Typography.Text>{edition}</Typography.Text>
              <Typography.Text type="secondary">{current.release.release_date}</Typography.Text>
            </Space>
          </Space>
        </Col>
        <Col><div className="about-release-mark">IT<span>OM</span></div></Col>
      </Row>
    </Card>

    <Row gutter={[18, 18]}>
      <Col xs={24} lg={16}>
        <Card title={<Space><HistoryOutlined />{english ? "What's new" : '本次更新'}</Space>}>
          <Typography.Title level={4}>{notes.title}</Typography.Title>
          <Timeline items={notes.highlights.map((item) => ({ children: item }))} />
          {notes.fixes.length > 0 && <><Divider orientation="left">{english ? 'Improvements' : '改进与修复'}</Divider><List size="small" dataSource={notes.fixes} renderItem={(item) => <List.Item>{item}</List.Item>} /></>}
          {notes.known_limits.length > 0 && <Alert showIcon type="info" style={{ marginTop: 18 }} message={english ? 'Current boundaries' : '当前边界'} description={<ul>{notes.known_limits.map((item) => <li key={item}>{item}</li>)}</ul>} />}
        </Card>
      </Col>
      <Col xs={24} lg={8}>
        <Space direction="vertical" size={18} style={{ width: '100%' }}>
          <Card title={english ? 'Product and developer' : '产品与开发者'}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label={english ? 'Developer' : '开发者'}>{developer}</Descriptions.Item>
              {vendor && <Descriptions.Item label={english ? 'Vendor' : '厂商'}>{vendor}</Descriptions.Item>}
              <Descriptions.Item label={english ? 'License' : '软件许可'}>{licenseName}</Descriptions.Item>
              <Descriptions.Item label={english ? 'Copyright' : '版权'}>© {branding?.legal.copyright_year || '2026'} {copyrightHolder}</Descriptions.Item>
            </Descriptions>
            {legalLinks.length > 0 && <Space wrap>{legalLinks.map((item) => <Button key={item.key} type="link" icon={item.icon} href={item.href} target="_blank" rel="noreferrer">{item.label}</Button>)}</Space>}
          </Card>
          <Card title={english ? 'Release history' : '版本历史'}>
            <List dataSource={history} renderItem={(item) => <List.Item><List.Item.Meta title={<Space><span>v{item.release.version}</span>{item.release.version === current.release.version && <Tag color="blue">{english ? 'Current' : '当前'}</Tag>}</Space>} description={`${item.release.release_date} · ${item.notes[lang].title}`} /></List.Item>} />
          </Card>
        </Space>
      </Col>
    </Row>
    <Typography.Text type="secondary"><LinkOutlined /> {english ? 'Software version is read-only and comes from the Git-controlled release manifest. Branding configuration versions are separate.' : '软件版本只读且来自 Git 发布清单，与界面品牌配置版本相互独立。'}</Typography.Text>
  </Space>;
}
