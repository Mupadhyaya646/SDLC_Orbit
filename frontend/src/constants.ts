import type { AgentRuntimeStatus, StageStatus } from './types'

export const STAGE_NAMES = ['Design', 'Build', 'Test', 'Review', 'Commit & PR', 'QA & UAT', 'Release & Docs']

export const STAGE_DESC = [
  'Analyzes the request, splits it into admin vs dev work, and proposes a plan for your approval.',
  'Implements declarative admin work and Apex/LWC dev work.',
  'Writes @isTest Apex test classes targeting 90%+ coverage.',
  'Reviews all code and returns a verdict; rejections loop back to the developer (capped).',
  'Mirrors changes, commits, pushes, validates against a target org and opens the PR - six human gates.',
  'Deploys to QA, then waits for the SME confirmation and UAT approval.',
  'PR approval and merge, Prod deploy, Prod confirmation, then the design document.',
]

export const AGENT_INITIALS: Record<string, string> = {
  'salesforce-design-agent': 'DS',
  'salesforce-admin-agent': 'AD',
  'salesforce-developer-agent': 'DV',
  'salesforce-unit-testing-agent': 'UT',
  'salesforce-code-review-agent': 'CR',
  'salesforce-devops-agent': 'DO',
  'github-commit-agent': 'GC',
  'salesforce-documentation-agent': 'DC',
  'pipeline-orchestrator': 'OR',
}

export const STAGE_AGENT_IDS: string[][] = [
  ['salesforce-design-agent'],
  ['salesforce-admin-agent', 'salesforce-developer-agent'],
  ['salesforce-unit-testing-agent'],
  ['salesforce-code-review-agent'],
  ['github-commit-agent'],
  ['salesforce-devops-agent', 'pipeline-orchestrator'],
  ['salesforce-devops-agent', 'salesforce-documentation-agent', 'pipeline-orchestrator'],
]

export const SL: Record<StageStatus, string> = {
  done: 'Done',
  awaiting: 'Awaiting you',
  running: 'In progress',
  idle: 'Not started',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

export const SC: Record<StageStatus, string> = {
  done: 'var(--ink)',
  awaiting: 'var(--red-text)',
  running: 'var(--blue)',
  idle: 'var(--muted)',
  failed: 'var(--red-text)',
  cancelled: 'var(--muted)',
}

export const AL: Record<AgentRuntimeStatus, string> = {
  idle: 'Idle',
  running: 'Running',
  done: 'Done',
  failed: 'Failed',
  awaiting: 'Awaiting input',
}

export const EXAMPLES: Array<[string, string]> = [
  [
    'Add a field and routing flow',
    'Add an Enrollment Source picklist to Enrollment__c, show it on the Patient Enrollment record page, and route Web Form enrollments to the Zepbound welcome journey queue. Leave the existing Enrollment_Welcome flow unchanged and add Apex test coverage for the routing.',
  ],
  [
    'Relax a validation rule',
    'Relax the Date_of_Birth validation rule on Contact so call center users can save records with an unknown birth year. Keep the rule active for web submissions and add test coverage.',
  ],
  [
    'Build a status history component',
    'Build a Lightning web component for the Patient Enrollment record page that lists the last five status changes with timestamps and the user who made each change.',
  ],
]

export const DEFAULT_ROSTER: Array<{ id: string; short: string }> = [
  { id: 'salesforce-design-agent', short: 'Analyzes the request, splits admin vs dev work, proposes a plan.' },
  { id: 'salesforce-admin-agent', short: 'Declarative Salesforce work: objects, fields, flows, permission sets.' },
  { id: 'salesforce-developer-agent', short: 'Apex, triggers, LWC, Visualforce, APIs.' },
  { id: 'salesforce-unit-testing-agent', short: 'Writes @isTest Apex test classes, 90%+ coverage target.' },
  { id: 'salesforce-code-review-agent', short: 'Reviews all code, returns a verdict.' },
  { id: 'salesforce-devops-agent', short: 'Final deploy step after code review passes.' },
  { id: 'github-commit-agent', short: 'Mirrors, commits, pushes, validates, optionally opens a PR.' },
  { id: 'salesforce-documentation-agent', short: 'Builds the LSC Design Document, publishes to Confluence or saves locally.' },
]
