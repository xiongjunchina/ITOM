import { ROUTE_PROJECT, type RequirementRow } from '../../api/types';

/**
 * A project association is not itself proof that a requirement was routed to
 * project delivery. Only the frozen implementation route may exclude it from
 * the Requirement Development candidate list.
 */
export function isRequirementDevelopmentTaskCandidate(requirement: RequirementRow): boolean {
  return (
    requirement.status === 'implementing'
    && !requirement.is_example
    && requirement.implementation_route !== ROUTE_PROJECT
    && requirement.can_manage_tasks === true
  );
}

/** Task maintainers need assignee options even when the workflow record itself is read-only. */
export function shouldLoadRequirementTaskMembers(canEdit: boolean, canManageTasks: boolean): boolean {
  return canEdit || canManageTasks;
}
