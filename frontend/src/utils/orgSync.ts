import { api } from '../api/client';
import type { FeishuConfig } from '../api/types';

/**
 * 触发组织同步并轮询直至完成（M35 异步化：后台执行，前端 3s 轮询状态）。
 * 返回最终统计；失败抛出含 error 的异常。最长等待 10 分钟。
 */
export async function runOrgSyncAndWait(
  source: string,
  onTick?: (elapsedSec: number) => void,
): Promise<Record<string, number>> {
  await api.post('/admin/org-sync', { source });
  const started = Date.now();
  for (;;) {
    await new Promise((r) => setTimeout(r, 3000));
    const cfg = await api.get<FeishuConfig>('/admin/feishu-config');
    const stats = (cfg.last_sync_stats ?? {}) as Record<string, unknown> & { status?: string; error?: string };
    if (stats.status === 'done') return stats as unknown as Record<string, number>;
    if (stats.status === 'failed') throw new Error(stats.error || '同步失败');
    onTick?.(Math.round((Date.now() - started) / 1000));
    if (Date.now() - started > 10 * 60_000) throw new Error('同步超时（10 分钟），请稍后查看结果');
  }
}
