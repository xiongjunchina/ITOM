/**
 * Records a workflow task's first real detail-page view.
 *
 * List refreshes, notification rendering and passive process bars intentionally
 * do not call this hook.  Only a user who can handle the current task causes
 * the backend to close the upstream correction window.
 */
import { useEffect, useRef } from 'react';
import { api } from '../api/client';
import type { AuthUser, TicketProcess } from '../api/types';
import { canHandleTask } from '../stores/auth';

export function useProcessTaskView(
  process: TicketProcess | null | undefined,
  user: AuthUser | null,
  onMarked?: () => void,
) {
  const attempted = useRef(new Set<string>());

  useEffect(() => {
    const step = process?.steps?.find((item) => item.seq === process.current_step_seq);
    if (!step?.task_id || step.task_status !== '待处理' || step.viewed_at || !canHandleTask(user, step)) return;
    // Administrators can inspect every record and dispatch work, but that is
    // not the next handler's first read.  Record a passive detail view only
    // when the administrator is explicitly the assigned handler; handling
    // actions themselves are recorded by the backend.
    const isAdmin = Boolean(user?.roles.includes('admin') || user?.permissions?.['*']);
    const isActualAssignee = Boolean(user?.person_id && step.assignee === user.person_id);
    if (isAdmin && !isActualAssignee) return;
    if (attempted.current.has(step.task_id)) return;
    attempted.current.add(step.task_id);
    void api.post(`/process-tasks/${step.task_id}/view`)
      .then(() => onMarked?.())
      .catch(() => attempted.current.delete(step.task_id!));
  }, [onMarked, process, user]);
}
