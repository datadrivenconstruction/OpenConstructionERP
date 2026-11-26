// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The overview shows a viewer the same actions as an editor: the buttons stay,
// disabled, each saying who can use it. An editor gets them enabled.

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { OverviewPanel } from '../OverviewPanel';
import type { Catalogue, Frame } from '../api';
import type { HseWrite } from '../hooks';

const FRAME = {
  id: 'f1',
  project_id: 'p1',
  state: 'draft',
  hazardous_work_codes: [],
  hazardous_works_assessed: false,
  duration_working_days: null,
  peak_workers: null,
  person_days: null,
  employers_count: null,
  planned_start: null,
  advance_notice_sent_on: null,
  advance_notice_reference: '',
  plan_status: 'none',
  plan_issued_on: null,
  later_works_status: 'none',
  notes: '',
  version: 1,
} as unknown as Frame;

const CATALOGUE = {
  id: 'c1',
  labels: null,
  jurisdiction: 'XX',
  topics: [],
  role_kinds: [],
  templates: [],
  hazardous_works: [],
  plan_elements: [],
  thresholds: {},
  link_kinds: [],
  item_statuses: [],
} as unknown as Catalogue;

const WRITE: HseWrite = { send: vi.fn(), pending: false, refusal: null };
const EDITOR_ONLY = 'Only an editor, manager or administrator can do this.';
const MANAGER_ONLY = 'Only a manager or administrator can do this.';

function panel(over: Record<string, unknown>) {
  return render(
    <OverviewPanel
      projectId="p1"
      frame={FRAME}
      catalogue={CATALOGUE}
      duties={null}
      readiness={undefined}
      summary={undefined}
      write={WRITE}
      canEdit={false}
      canManage={false}
      canApprove={false}
      {...over}
    />,
  );
}

describe('HSE frame overview read access', () => {
  it('keeps every action for a viewer, disabled, with who can use it', () => {
    panel({ editReason: EDITOR_ONLY, manageReason: MANAGER_ONLY, approveReason: MANAGER_ONLY });
    const templates = screen.getByTestId('apply-templates');
    expect(templates).toBeDisabled();
    expect(templates).toHaveAttribute('title', EDITOR_ONLY);
    const submit = screen.getByTestId('frame-submit');
    expect(submit).toBeDisabled();
    expect(submit).toHaveAttribute('title', MANAGER_ONLY);
    expect(screen.getByTestId('facts-save')).toBeDisabled();
  });

  it('enables them for a manager', () => {
    panel({ canEdit: true, canManage: true, canApprove: true });
    expect(screen.getByTestId('apply-templates')).toBeEnabled();
    expect(screen.getByTestId('frame-submit')).toBeEnabled();
    expect(screen.getByTestId('apply-templates')).not.toHaveAttribute('title');
  });
});
