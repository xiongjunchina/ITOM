import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('new independent panels stay after the original ticket and requirement detail content', () => {
  const ticket = read('../src/pages/itsm/TicketDetail.tsx');
  const ticketRelationsIndex = ticket.indexOf('<RecordRelationsPanel');
  const ticketInvestmentIndex = ticket.indexOf('<InvestmentPanel');
  const ticketVisibleEndIndex = ticket.indexOf('{/* 状态流转 Modal */}');
  assert.ok(
    ticketRelationsIndex > ticket.lastIndexOf('{(detail.solution || detail.root_cause) && ('),
    'ticket relations panel must follow every original visible detail section',
  );
  assert.ok(
    ticketInvestmentIndex > ticketRelationsIndex,
    'ticket investment panel must follow the relations panel in the bottom group',
  );
  assert.ok(
    ticketInvestmentIndex < ticketVisibleEndIndex,
    'ticket bottom panel group must remain visible page content rather than modal content',
  );

  const requirement = read('../src/pages/requirements/RequirementDetail.tsx');
  const requirementRelationsIndex = requirement.indexOf('<RecordRelationsPanel');
  const requirementInvestmentIndex = requirement.indexOf('<InvestmentPanel');
  const requirementVisibleEndIndex = requirement.indexOf('{/* 编辑基本信息 Modal */}');
  assert.ok(
    requirementRelationsIndex > requirement.lastIndexOf('{/* 关闭收尾'),
    'requirement relations panel must follow every original visible detail section',
  );
  assert.ok(
    requirementInvestmentIndex > requirementRelationsIndex,
    'requirement investment panel must follow the relations panel in the bottom group',
  );
  assert.ok(
    requirementInvestmentIndex < requirementVisibleEndIndex,
    'requirement bottom panel group must remain visible page content rather than modal content',
  );
});

test('relations panels stay at the bottom of problem and project detail content', () => {
  const problem = read('../src/pages/itsm/ProblemDetail.tsx');
  const problemRelationsIndex = problem.indexOf('<RecordRelationsPanel');
  const problemVisibleEndIndex = problem.indexOf('{/* 状态流转 Modal');
  assert.ok(
    problemRelationsIndex > problem.lastIndexOf("t('itsm.problem.linkedTicketsCount'"),
    'problem relations panel must follow the original linked-ticket section',
  );
  assert.ok(
    problemRelationsIndex < problemVisibleEndIndex,
    'problem relations panel must remain visible page content rather than modal content',
  );

  const project = read('../src/pages/projects/ProjectDetail.tsx');
  const projectRelationsIndex = project.indexOf('<RecordRelationsPanel');
  const projectProgressIndex = project.indexOf("<Card title={t('proj.progress')}");
  const projectOverviewEndIndex = project.indexOf('// ----- 进度 -----');
  assert.ok(
    projectRelationsIndex > projectProgressIndex,
    'project relations panel must follow the original overview progress section',
  );
  assert.ok(
    projectRelationsIndex < projectOverviewEndIndex,
    'project relations panel must remain in the overview content rather than later tab definitions',
  );
});
