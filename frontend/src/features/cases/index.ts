// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases feature - public surface.

export { CasesPage } from './CasesPage';
export { CaseEditorPage } from './CaseEditorPage';
export { PlaybookRunner } from './PlaybookRunner';
export { PLAYBOOKS, getPlaybook } from './playbooks';
export { useCasesStore, EMPTY_PROGRESS } from './useCasesStore';
export { useAuthoredCases, useAuthoredCase, useCaseMutations } from './useCustomCases';
export { authoredPlaybookId, caseIdFromPlaybookId, caseToPlaybook } from './api';
// The market a UI language speaks for and the ordering that follows: one
// helper for the hub, the dashboard and anything else that leads with a
// reader's market, so no second copy can drift.
export { homeMarketFirst, homeMarketForLanguage } from './homeMarket';
export { regionDisplayName } from './regions';
export type { Playbook, PlaybookStep, PlaybookProgress } from './types';
