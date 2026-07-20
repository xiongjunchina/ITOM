import { useEffect, useState } from 'react';
import { Alert, Button, Card, Col, Form, Input, Radio, Row, Select, Space, Switch, Tabs, message } from 'antd';
import { HistoryOutlined, SaveOutlined } from '@ant-design/icons';
import { api } from '../../api/client';
import { type BrandingVersion, type UiBrandingConfig, useBrandingStore } from '../../stores/branding';
import ImageCropUpload from '../../components/ImageCropUpload';

interface AdminBranding { draft: BrandingVersion; published: BrandingVersion }
type FormValue = UiBrandingConfig;
const paths = ['manager_landing','operator_landing','requester_landing','noc_landing'];

export default function UiBranding() {
  const [form] = Form.useForm<FormValue>();
  const [loading, setLoading] = useState(true);
  const [published, setPublished] = useState<BrandingVersion | null>(null);
  const [history, setHistory] = useState<BrandingVersion[]>([]);
  const setCurrent = useBrandingStore((s) => s.setCurrent);
  const load = async () => { setLoading(true); try { const data = await api.get<AdminBranding>('/admin/ui-branding'); form.setFieldsValue(data.draft.config); setPublished(data.published); setHistory((await api.getList<BrandingVersion>('/admin/ui-branding/history')).items); } finally { setLoading(false); } };
  useEffect(() => { void load(); }, []);
  const save = async () => { const config = await form.validateFields(); await api.put('/admin/ui-branding/draft', { config }); message.success('草稿已保存'); };
  const preview = async () => { const config = await form.validateFields(); setCurrent({ id: null, version: 0, status: 'preview', config }); message.info('已在当前浏览器临时预览草稿，刷新页面恢复线上版本'); };
  const publish = async () => { await save(); const value = await api.post<BrandingVersion>('/admin/ui-branding/publish'); setPublished(value); setCurrent(value); message.success(`版本 v${value.version} 已发布`); void load(); };
  const reset = async () => { const value = await api.post<BrandingVersion>('/admin/ui-branding/reset'); form.setFieldsValue(value.config); message.success('草稿已恢复默认值'); };
  const upload = (kind: string, field: string) => async (file: File) => {
    // 上传前快照整份表单；图片上传是异步过程，不能让无关字段被服务器旧草稿覆盖。
    const snapshot = JSON.parse(JSON.stringify(form.getFieldsValue(true))) as FormValue;
    const [section, name] = field.split('.') as ['brand' | 'login', string];
    const result = await api.upload<{ url: string }>(`/admin/ui-branding/assets?kind=${kind}`, file);
    const next = {
      ...snapshot,
      [section]: { ...snapshot[section], [name]: result.url },
    } as FormValue;
    form.setFieldsValue(next);
    await api.put('/admin/ui-branding/draft', { config: next });
    message.success('裁剪图片和当前表单已保存到草稿');
  };
  const field = (section: string, name: string, label: string) => <Form.Item name={[section,name]} label={label}><Input maxLength={300} /></Form.Item>;
  const asset = (kind: string, label: string, section='brand') => {
    const square = kind === 'logo_square' || kind === 'favicon';
    const background = kind === 'login_background';
    const fieldName = background ? 'background_image_url' : `${kind}_url`;
    return <Form.Item key={kind} label={label} extra={`裁剪比例 ${background ? '16:9' : square ? '1:1' : '4:1'}`}><Space.Compact block><Form.Item name={[section, fieldName]} noStyle><Input /></Form.Item><ImageCropUpload aspect={background ? 16/9 : square ? 1 : 4} outputWidth={background ? 1920 : square ? 512 : 1200} onConfirm={upload(kind,`${section}.${fieldName}`)} /></Space.Compact></Form.Item>;
  };
  return <Card loading={loading} title="界面与品牌" extra={<Space><Button onClick={() => void reset()}>恢复默认</Button><Button icon={<SaveOutlined />} onClick={() => void save()}>保存草稿</Button><Button onClick={() => void preview()}>预览草稿</Button><Button type="primary" onClick={() => void publish()}>发布</Button></Space>}>
    <Alert showIcon type="info" message={`当前线上版本：${published?.version ? `v${published.version}` : '系统默认'}。配置先保存为草稿，发布后全局生效；个人主题与密度偏好优先。`} style={{marginBottom:16}} />
    <Form form={form} layout="vertical"><Tabs items={[
      {key:'brand',label:'品牌标识',children:<Row gutter={24}><Col span={12}>{field('brand','system_name_zh','系统名称（中文）')}{field('brand','system_name_en','System name')}{field('brand','short_name_zh','简称（中文）')}{field('brand','short_name_en','Short name')}{field('brand','description_zh','系统简介（中文）')}{field('brand','description_en','Description')}{field('brand','browser_title_suffix','浏览器标题后缀')}</Col><Col span={12}>{asset('logo_light','浅色背景横版 Logo')}{asset('logo_dark','深色背景横版 Logo')}{asset('logo_square','折叠/方形 Logo')}{asset('favicon','Favicon')}</Col></Row>},
      {key:'login',label:'登录门户',children:<Row gutter={24}><Col span={12}>{field('login','title_zh','登录标题（中文）')}{field('login','title_en','Login title')}{field('login','description_zh','登录说明（中文）')}{field('login','description_en','Login description')}{field('login','notice_zh','欢迎语/公告（中文）')}{field('login','notice_en','Welcome message')}{field('login','help_url','帮助链接')}{field('login','support_text','IT 支持信息')}{field('login','privacy_url','隐私政策链接')}{field('login','terms_url','使用条款链接')}{field('login','copyright','版权信息')}</Col><Col span={12}><Form.Item name={['login','show_logo']} label="显示 Logo" valuePropName="checked"><Switch /></Form.Item><Form.Item name={['login','layout']} label="布局"><Radio.Group options={[{label:'居中',value:'center'},{label:'左右分栏',value:'split'}]} /></Form.Item><Form.Item name={['login','background_type']} label="背景"><Select options={['solid','pattern','image'].map(value=>({value,label:value}))}/></Form.Item>{field('login','background_color','背景色')}{asset('login_background','登录背景图片','login')}</Col></Row>},
      {key:'appearance',label:'应用外观',children:<Row gutter={24}><Col span={8}><Form.Item name={['appearance','primary_color']} label="主色" rules={[{pattern:/^#[0-9a-fA-F]{6}$/,message:'请输入六位十六进制颜色'}]}><Input type="color" /></Form.Item><Form.Item name={['appearance','default_theme']} label="默认主题"><Select options={['light','dark','system'].map(value=>({value,label:value}))}/></Form.Item></Col><Col span={8}><Form.Item name={['appearance','default_density']} label="默认密度"><Select options={['default','compact'].map(value=>({value,label:value}))}/></Form.Item><Form.Item name={['appearance','sidebar_theme']} label="侧栏"><Select options={['light','dark'].map(value=>({value,label:value}))}/></Form.Item></Col><Col span={8}><Form.Item name={['appearance','show_system_name_in_header']} label="顶栏显示系统名称" valuePropName="checked"><Switch /></Form.Item></Col></Row>},
      {key:'roles',label:'角色体验',children:<>{paths.map((name)=><Form.Item key={name} name={['roles',name]} label={name}><Input placeholder="例如 /dashboard" /></Form.Item>)}</>},
      {key:'notice',label:'公告与环境',children:<Row gutter={24}><Col span={12}><Form.Item name={['announcement','enabled']} label="启用顶部公告" valuePropName="checked"><Switch /></Form.Item>{field('announcement','text_zh','公告（中文）')}{field('announcement','text_en','Announcement')}{field('announcement','starts_at','开始时间（ISO）')}{field('announcement','ends_at','结束时间（ISO）')}<Form.Item name={['announcement','type']} label="类型"><Select options={['info','warning','maintenance'].map(value=>({value,label:value}))}/></Form.Item><Form.Item name={['announcement','dismissible']} label="允许关闭" valuePropName="checked"><Switch /></Form.Item><Form.Item name={['announcement','show_on_login']} label="登录页显示" valuePropName="checked"><Switch /></Form.Item></Col><Col span={12}><Form.Item name={['environment','label']} label="环境"><Select options={['production','test','development'].map(value=>({value,label:value}))}/></Form.Item><Form.Item name={['environment','show_marker']} label="显示非生产环境标记" valuePropName="checked"><Switch /></Form.Item></Col></Row>},
      {key:'history',label:<span><HistoryOutlined /> 版本历史</span>,children:<Space direction="vertical" style={{width:'100%'}}>{history.map(v=><Card size="small" key={v.id}><Space style={{justifyContent:'space-between',width:'100%'}}><span>v{v.version} · {v.updated_at || ''}</span><Button disabled={v.version===published?.version} onClick={async()=>{const next=await api.post<BrandingVersion>(`/admin/ui-branding/rollback/${v.version}`); setCurrent(next); message.success(`已回滚并发布为 v${next.version}`); void load();}}>回滚</Button></Space></Card>)}</Space>},
    ]}/></Form>
  </Card>;
}
