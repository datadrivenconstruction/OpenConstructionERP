// OpenConstructionERP — DataDrivenConstruction (DDC)
// Tests for the free-text route-unification seam on Stage1Intake.
//
// WP6 mounts the shared conversational IntakePanel as the free-text front door
// of /ai-estimator. The seam is the `textSlot` prop: when supplied, the free
// text tab renders the guided dialogue instead of the plain textarea + the
// direct "Start AI estimate" run button (the old parse_text_scope path), while
// the files / BIM / documents tabs keep their direct start path untouched.

import { describe, it, expect, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

import { Stage1Intake, type Stage1IntakeProps } from '../Stage1Source';

afterEach(cleanup);

const SLOT_MARKER = 'GUIDED-DIALOGUE-SLOT';

function makeProps(overrides: Partial<Stage1IntakeProps> = {}): Stage1IntakeProps {
  return {
    projectId: 'proj-1',
    sourceKind: 'text',
    onSourceKind: vi.fn(),
    text: '',
    onText: vi.fn(),
    files: [],
    onFiles: vi.fn(),
    bimModels: [],
    bimModelsLoading: false,
    selectedModelId: null,
    onSelectModel: vi.fn(),
    documents: [],
    selectedDocIds: [],
    onToggleDoc: vi.fn(),
    canStart: true,
    starting: false,
    onStart: vi.fn(),
    ...overrides,
  };
}

describe('Stage1Intake free-text unification (WP6)', () => {
  it('renders the guided dialogue slot for the text tab instead of the plain run starter', () => {
    render(
      <Stage1Intake
        {...makeProps({ sourceKind: 'text' })}
        textSlot={<div>{SLOT_MARKER}</div>}
      />,
    );

    // The conversational front door is mounted.
    expect(screen.getByText(SLOT_MARKER)).toBeInTheDocument();

    // The old parse_text_scope path is suppressed: no free-text textarea and no
    // direct "Start AI estimate" button (the panel owns its own controls).
    expect(screen.queryByText('Start AI estimate')).not.toBeInTheDocument();
    expect(document.querySelector('textarea')).toBeNull();
  });

  it('keeps the plain textarea + Start button when no slot is supplied (back-compat)', () => {
    render(<Stage1Intake {...makeProps({ sourceKind: 'text' })} />);

    expect(document.querySelector('textarea')).not.toBeNull();
    expect(screen.getByText('Start AI estimate')).toBeInTheDocument();
  });

  it('does not show the guided slot for non-text tabs even when a slot is passed', () => {
    const onStart = vi.fn();
    render(
      <Stage1Intake
        {...makeProps({ sourceKind: 'files', onStart })}
        textSlot={<div>{SLOT_MARKER}</div>}
      />,
    );

    // Files tab keeps the direct path: the slot is hidden, the Start button is
    // present (files carry real quantities and need no questionnaire).
    expect(screen.queryByText(SLOT_MARKER)).not.toBeInTheDocument();
    expect(screen.getByText('Start AI estimate')).toBeInTheDocument();
  });

  it('always renders all four source tabs so the user can switch sources', () => {
    render(
      <Stage1Intake
        {...makeProps({ sourceKind: 'text' })}
        textSlot={<div>{SLOT_MARKER}</div>}
      />,
    );

    expect(screen.getByText('Free text')).toBeInTheDocument();
    expect(screen.getByText('Upload files')).toBeInTheDocument();
    expect(screen.getByText('BIM / CAD model')).toBeInTheDocument();
    expect(screen.getByText('Project documents')).toBeInTheDocument();
  });
});
