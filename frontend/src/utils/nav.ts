import { useNavigate } from 'react-router-dom';

/**
 * 详情页「返回」（M26）：优先原路返回（保留来源页的筛选/分页），
 * 无站内历史（通知/直链/新标签打开）时回退到给定列表页。
 */
export function useGoBack() {
  const navigate = useNavigate();
  return (fallback: string) => {
    const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0;
    if (idx > 0) navigate(-1);
    else navigate(fallback, { replace: true });
  };
}
