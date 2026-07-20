import { useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import { Button, Modal, Slider, Space, Typography, message } from 'antd';
import { RotateRightOutlined, UploadOutlined, ZoomInOutlined } from '@ant-design/icons';

interface Props {
  aspect: number;
  label?: string;
  outputWidth: number;
  onConfirm: (file: File) => Promise<void>;
}

const VIEWPORT_WIDTH = 480;

export default function ImageCropUpload({ aspect, label = '选择并裁剪', outputWidth, onConfirm }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState('');
  const [filename, setFilename] = useState('image');
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [drag, setDrag] = useState<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const [saving, setSaving] = useState(false);
  const viewportHeight = Math.round(VIEWPORT_WIDTH / aspect);
  const baseScale = useMemo(() => image ? Math.max(VIEWPORT_WIDTH / image.naturalWidth, viewportHeight / image.naturalHeight) : 1, [image, viewportHeight]);

  useEffect(() => () => { if (source) URL.revokeObjectURL(source); }, [source]);

  const choose = (file?: File) => {
    if (!file) return;
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
      message.error('裁剪支持 PNG、JPEG、WebP 图片'); return;
    }
    if (source) URL.revokeObjectURL(source);
    const url = URL.createObjectURL(file);
    const next = new Image();
    next.onload = () => { setImage(next); setOpen(true); };
    next.onerror = () => message.error('无法读取该图片');
    next.src = url;
    setSource(url); setFilename(file.name.replace(/\.[^.]+$/, '')); setZoom(1); setRotation(0); setOffset({ x: 0, y: 0 });
    if (inputRef.current) inputRef.current.value = '';
  };

  const move = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drag) return;
    setOffset({ x: drag.ox + event.clientX - drag.x, y: drag.oy + event.clientY - drag.y });
  };

  const confirm = async () => {
    if (!image) return;
    setSaving(true);
    try {
      const outputHeight = Math.round(outputWidth / aspect);
      const canvas = document.createElement('canvas');
      canvas.width = outputWidth; canvas.height = outputHeight;
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('Canvas unavailable');
      const ratio = outputWidth / VIEWPORT_WIDTH;
      ctx.scale(ratio, ratio);
      ctx.translate(VIEWPORT_WIDTH / 2 + offset.x, viewportHeight / 2 + offset.y);
      ctx.rotate(rotation * Math.PI / 180);
      ctx.scale(baseScale * zoom, baseScale * zoom);
      ctx.drawImage(image, -image.naturalWidth / 2, -image.naturalHeight / 2);
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png', 0.95));
      if (!blob) throw new Error('Crop failed');
      await onConfirm(new File([blob], `${filename}-cropped.png`, { type: 'image/png' }));
      setOpen(false);
    } catch {
      message.error('图片裁剪或上传失败');
    } finally { setSaving(false); }
  };

  return <>
    <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(event) => choose(event.target.files?.[0])} />
    <Button icon={<UploadOutlined />} onClick={() => inputRef.current?.click()}>{label}</Button>
    <Modal title="裁剪图片" open={open} width={620} okText="使用此区域" cancelText="取消" confirmLoading={saving} onOk={() => void confirm()} onCancel={() => setOpen(false)} destroyOnClose>
      <Typography.Paragraph type="secondary">拖动图片选择使用区域；可缩放和旋转。虚线框内即最终输出内容。</Typography.Paragraph>
      <div
        role="application" aria-label="图片裁剪区域" className="image-crop-viewport"
        style={{ width: VIEWPORT_WIDTH, height: viewportHeight }}
        onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); setDrag({ x: event.clientX, y: event.clientY, ox: offset.x, oy: offset.y }); }}
        onPointerMove={move} onPointerUp={() => setDrag(null)} onPointerCancel={() => setDrag(null)}
      >
        {source && <img src={source} alt="待裁剪图片" draggable={false} style={{ width: image?.naturalWidth, height: image?.naturalHeight, transform: `translate(-50%, -50%) translate(${offset.x}px, ${offset.y}px) scale(${baseScale * zoom}) rotate(${rotation}deg)` }} />}
        <span className="image-crop-grid" aria-hidden="true" />
      </div>
      <Space direction="vertical" size={14} style={{ width: '100%', marginTop: 20 }}>
        <div className="image-crop-control"><ZoomInOutlined /><span>缩放</span><Slider min={1} max={3} step={0.01} value={zoom} onChange={setZoom} /></div>
        <div className="image-crop-control"><RotateRightOutlined /><span>旋转</span><Slider min={-180} max={180} step={1} value={rotation} onChange={setRotation} /></div>
        <Space><Button onClick={() => setRotation((value) => value - 90)}>左转 90°</Button><Button onClick={() => setRotation((value) => value + 90)}>右转 90°</Button><Button onClick={() => { setZoom(1); setRotation(0); setOffset({x:0,y:0}); }}>重置</Button></Space>
      </Space>
    </Modal>
  </>;
}
