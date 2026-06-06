// OpenConstructionERP — DataDrivenConstruction (DDC)
// Tests that the shared IntakePanel is the conversational front door.
//
// WP6 mounts this panel as the free-text entry of /ai-estimator. Before any
// run exists the panel must show the guided-estimate collect-request (a single
// free-text line plus "Start guided estimate"), NOT a plain run starter. The
// intake API is only called on user actions, so the collect-request renders
// without any network.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import React from 'react';

// Guard against accidental network on mount: the panel must render the
// collect-request without calling any intake endpoint.
const startSpy = vi.fn();
vi.mock('../api', () => ({
  intakeApi: {
    start: (...args: unknown[]) => {
      startSpy(...args);
      return Promise.resolve(null);
    },
    get: vi.fn(),
    answer: vi.fn(),
    confirmParameters: vi.fn(),
    editPackages: vi.fn(),
    finish: vi.fn(),
  },
}));

import { IntakePanel } from '../IntakePanel';

afterEach(() => {
  cleanup();
  startSpy.mockClear();
});

describe('IntakePanel as the /ai-estimator free-text front door (WP6)', () => {
  it('renders the guided collect-request, not a parse-text run starter', () => {
    render(<IntakePanel projectId="proj-1" onFinished={vi.fn()} />);

    // The guided front door: a free-text request box and the start control.
    expect(screen.getByText('Start guided estimate')).toBeInTheDocument();
    expect(document.querySelector('#aiest-intake-text')).not.toBeNull();
    // And an offline escape hatch for no-key mode.
    expect(screen.getByText("I'd rather fill a form")).toBeInTheDocument();

    // No network fired on mount.
    expect(startSpy).not.toHaveBeenCalled();
  });

  it('seeds the request box from initialText (carried from the page textarea)', () => {
    render(
      <IntakePanel projectId="proj-1" initialText="kitchen estimate please" onFinished={vi.fn()} />,
    );
    const box = document.querySelector('#aiest-intake-text') as HTMLTextAreaElement | null;
    expect(box?.value).toBe('kitchen estimate please');
  });
});
