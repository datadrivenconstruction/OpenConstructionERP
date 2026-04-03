// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { ConflictResolutionPanel } from './ConflictResolutionPanel';
import type { ConflictItem } from '../hooks/useConflictDetection';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeConflict(overrides: Partial<ConflictItem> = {}): ConflictItem {
  return {
    id: 'c1',
    field: 'unit_rate',
    positionOrdinal: '01.02.001',
    localValue: '150.00',
    remoteValue: '175.00',
    remoteUser: 'Alice',
    timestamp: new Date('2024-06-01T10:00:00'),
    ...overrides,
  };
}

function renderPanel(
  conflicts: ConflictItem[],
  onResolve = vi.fn(),
  onDismiss = vi.fn(),
) {
  return render(
    <ConflictResolutionPanel
      conflicts={conflicts}
      onResolve={onResolve}
      onDismiss={onDismiss}
    />,
  );
}

// ---------------------------------------------------------------------------
// Suite 1: Rendering
// ---------------------------------------------------------------------------

describe('ConflictResolutionPanel — rendering', () => {
  it('renders nothing when conflicts list is empty', () => {
    const { container } = renderPanel([]);
    // The component returns null — nothing inside the test container
    expect(container.firstChild).toBeNull();
  });

  it('renders the panel header when conflicts are present', () => {
    renderPanel([makeConflict()]);
    expect(screen.getByText('Merge Conflict Detected')).toBeInTheDocument();
    expect(
      screen.getByText(/A remote collaborator edited the same field/),
    ).toBeInTheDocument();
  });

  it('shows positionOrdinal and field in the info bar', () => {
    renderPanel([makeConflict()]);
    expect(screen.getByText('01.02.001')).toBeInTheDocument();
    expect(screen.getByText('unit_rate')).toBeInTheDocument();
  });

  it('shows remote user name in the info bar', () => {
    renderPanel([makeConflict({ remoteUser: 'Bob Smith' })]);
    expect(screen.getByText('Bob Smith')).toBeInTheDocument();
  });

  it('renders local and remote values side-by-side', () => {
    renderPanel([makeConflict()]);
    expect(screen.getByTestId('value-local')).toHaveTextContent('150.00');
    expect(screen.getByTestId('value-remote')).toHaveTextContent('175.00');
  });

  it('renders "Your version" and remote-user version labels', () => {
    renderPanel([makeConflict({ remoteUser: 'Carol' })]);
    expect(screen.getByText('Your version')).toBeInTheDocument();
    expect(screen.getByText('Their version')).toBeInTheDocument();
    // remote user name also appears in the card subtitle
    const theirCard = screen.getByTestId('value-remote').closest('[class*="rounded"]')!;
    expect(within(theirCard as HTMLElement).getByText('· Carol')).toBeInTheDocument();
  });

  it('shows three resolution controls: Keep mine, Accept theirs, Manual merge', () => {
    renderPanel([makeConflict()]);
    expect(screen.getByTestId('btn-keep-mine')).toBeInTheDocument();
    expect(screen.getByTestId('btn-accept-theirs')).toBeInTheDocument();
    expect(screen.getByTestId('btn-manual-merge')).toBeInTheDocument();
  });

  it('does NOT show navigation footer for a single conflict', () => {
    renderPanel([makeConflict()]);
    expect(screen.queryByText('Previous')).not.toBeInTheDocument();
    expect(screen.queryByText('Next')).not.toBeInTheDocument();
  });

  it('shows navigation footer and counter when multiple conflicts exist', () => {
    renderPanel([
      makeConflict({ id: 'c1' }),
      makeConflict({ id: 'c2', positionOrdinal: '01.02.002' }),
    ]);
    expect(screen.getByText(/1 \/ 2/)).toBeInTheDocument();
    expect(screen.getByText('← Previous')).toBeInTheDocument();
    expect(screen.getByText('Next →')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Suite 2: Resolution actions
// ---------------------------------------------------------------------------

describe('ConflictResolutionPanel — resolution actions', () => {
  it('calls onResolve with keep_mine when "Keep mine" is clicked', () => {
    const onResolve = vi.fn();
    renderPanel([makeConflict({ id: 'c-keep' })], onResolve);
    fireEvent.click(screen.getByTestId('btn-keep-mine'));
    expect(onResolve).toHaveBeenCalledWith('c-keep', 'keep_mine');
    expect(onResolve).toHaveBeenCalledTimes(1);
  });

  it('calls onResolve with accept_theirs when "Accept theirs" is clicked', () => {
    const onResolve = vi.fn();
    renderPanel([makeConflict({ id: 'c-accept' })], onResolve);
    fireEvent.click(screen.getByTestId('btn-accept-theirs'));
    expect(onResolve).toHaveBeenCalledWith('c-accept', 'accept_theirs');
  });

  it('shows manual merge input after clicking "Manual merge..."', () => {
    renderPanel([makeConflict()]);
    expect(screen.queryByTestId('manual-merge-input')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('btn-manual-merge'));
    expect(screen.getByTestId('manual-merge-input')).toBeInTheDocument();
  });

  it('calls onResolve with manual resolution and typed value', () => {
    const onResolve = vi.fn();
    renderPanel([makeConflict({ id: 'c-manual' })], onResolve);
    fireEvent.click(screen.getByTestId('btn-manual-merge'));
    const input = screen.getByTestId('manual-merge-input');
    fireEvent.change(input, { target: { value: '162.50' } });
    fireEvent.click(screen.getByTestId('btn-apply-manual'));
    expect(onResolve).toHaveBeenCalledWith('c-manual', 'manual', '162.50');
  });

  it('"Apply merged value" button is disabled when manual input is empty', () => {
    renderPanel([makeConflict()]);
    fireEvent.click(screen.getByTestId('btn-manual-merge'));
    const applyBtn = screen.getByTestId('btn-apply-manual');
    // Input is empty by default
    expect(applyBtn).toBeDisabled();
    // Type something → button becomes enabled
    const input = screen.getByTestId('manual-merge-input');
    fireEvent.change(input, { target: { value: '99' } });
    expect(applyBtn).not.toBeDisabled();
  });

  it('cancelling manual mode hides the input and re-shows the link', () => {
    renderPanel([makeConflict()]);
    fireEvent.click(screen.getByTestId('btn-manual-merge'));
    expect(screen.getByTestId('manual-merge-input')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Cancel'));
    expect(screen.queryByTestId('manual-merge-input')).not.toBeInTheDocument();
    expect(screen.getByTestId('btn-manual-merge')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Suite 3: Dismiss behaviour
// ---------------------------------------------------------------------------

describe('ConflictResolutionPanel — dismiss', () => {
  it('calls onDismiss when close button (X) is clicked', () => {
    const onDismiss = vi.fn();
    renderPanel([makeConflict()], vi.fn(), onDismiss);
    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('calls onDismiss when Escape key is pressed', () => {
    const onDismiss = vi.fn();
    renderPanel([makeConflict()], vi.fn(), onDismiss);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('calls onDismiss when backdrop is clicked', () => {
    const onDismiss = vi.fn();
    renderPanel([makeConflict()], vi.fn(), onDismiss);
    // The backdrop is the outermost div with role="dialog"
    const backdrop = screen.getByRole('dialog');
    // Click the backdrop itself (not the inner panel)
    fireEvent.click(backdrop);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// Suite 4: Multi-conflict navigation
// ---------------------------------------------------------------------------

describe('ConflictResolutionPanel — multi-conflict navigation', () => {
  const conflicts: ConflictItem[] = [
    makeConflict({ id: 'c1', positionOrdinal: '01.01', field: 'description', localValue: 'Concrete wall', remoteValue: 'RC Wall' }),
    makeConflict({ id: 'c2', positionOrdinal: '01.02', field: 'unit_rate', localValue: '200', remoteValue: '220' }),
    makeConflict({ id: 'c3', positionOrdinal: '01.03', field: 'quantity', localValue: '10', remoteValue: '12' }),
  ];

  it('starts on the first conflict', () => {
    renderPanel(conflicts);
    expect(screen.getByText('01.01')).toBeInTheDocument();
    expect(screen.getByText('description')).toBeInTheDocument();
  });

  it('navigates to next conflict on "Next →" click', () => {
    renderPanel(conflicts);
    fireEvent.click(screen.getByText('Next →'));
    expect(screen.getByText('01.02')).toBeInTheDocument();
    expect(screen.getByText('unit_rate')).toBeInTheDocument();
  });

  it('"Previous" is disabled on first conflict', () => {
    renderPanel(conflicts);
    const prev = screen.getByText('← Previous');
    // The button renders as a <button disabled> when at index 0
    expect(prev).toBeDisabled();
  });

  it('"Next" is disabled on last conflict', () => {
    renderPanel(conflicts);
    // Navigate to last (3 conflicts → need 2 clicks)
    fireEvent.click(screen.getByText('Next →'));
    fireEvent.click(screen.getByText('Next →'));
    const next = screen.getByText('Next →');
    expect(next).toBeDisabled();
  });

  it('dot indicators update current index when clicked', () => {
    renderPanel(conflicts);
    // Third dot → index 2
    const dots = screen.getAllByRole('button', { name: /Conflict \d/ });
    fireEvent.click(dots[2]);
    expect(screen.getByText('01.03')).toBeInTheDocument();
  });

  it('shows counter X / N for multi-conflict list', () => {
    renderPanel(conflicts);
    expect(screen.getByText('1 / 3')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Next →'));
    expect(screen.getByText('2 / 3')).toBeInTheDocument();
  });

  it('resolving a conflict removes it and shows the next one', () => {
    const onResolve = vi.fn();
    // Use a clone so the mock can simulate removal
    const localConflicts = [...conflicts];
    const { rerender } = render(
      <ConflictResolutionPanel
        conflicts={localConflicts}
        onResolve={onResolve}
        onDismiss={vi.fn()}
      />,
    );
    // Resolve first conflict → "keep mine"
    fireEvent.click(screen.getByTestId('btn-keep-mine'));
    expect(onResolve).toHaveBeenCalledWith('c1', 'keep_mine');

    // Simulate parent removing the resolved conflict
    rerender(
      <ConflictResolutionPanel
        conflicts={[conflicts[1], conflicts[2]]}
        onResolve={onResolve}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByText('01.02')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Suite 5: Accessibility
// ---------------------------------------------------------------------------

describe('ConflictResolutionPanel — accessibility', () => {
  it('has role="dialog" and aria-modal on the outer wrapper', () => {
    renderPanel([makeConflict()]);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
  });

  it('close button has accessible label', () => {
    renderPanel([makeConflict()]);
    expect(screen.getByRole('button', { name: /close/i })).toBeInTheDocument();
  });

  it('local value container is labelled "Your version"', () => {
    renderPanel([makeConflict()]);
    expect(screen.getByText('Your version')).toBeInTheDocument();
  });

  it('remote value container is labelled "Their version"', () => {
    renderPanel([makeConflict()]);
    expect(screen.getByText('Their version')).toBeInTheDocument();
  });

  it('manual merge textarea has a visible label', () => {
    renderPanel([makeConflict()]);
    fireEvent.click(screen.getByTestId('btn-manual-merge'));
    expect(screen.getByText('Enter merged value')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Suite 6: Edge cases
// ---------------------------------------------------------------------------

describe('ConflictResolutionPanel — edge cases', () => {
  it('renders empty string values without crashing', () => {
    renderPanel([makeConflict({ localValue: '', remoteValue: '' })]);
    expect(screen.getByTestId('value-local')).toBeInTheDocument();
    expect(screen.getByTestId('value-remote')).toBeInTheDocument();
  });

  it('renders long values without breaking layout', () => {
    const longValue = 'A'.repeat(500);
    renderPanel([makeConflict({ localValue: longValue, remoteValue: longValue })]);
    expect(screen.getByTestId('value-local')).toHaveTextContent(longValue);
  });

  it('manual mode resets when switching to another conflict', () => {
    const multiConflicts = [
      makeConflict({ id: 'c1' }),
      makeConflict({ id: 'c2', positionOrdinal: '02.01' }),
    ];
    renderPanel(multiConflicts);
    // Open manual mode on conflict 1
    fireEvent.click(screen.getByTestId('btn-manual-merge'));
    expect(screen.getByTestId('manual-merge-input')).toBeInTheDocument();
    // Navigate to conflict 2
    fireEvent.click(screen.getByText('Next →'));
    // Manual input should be gone for the new conflict
    expect(screen.queryByTestId('manual-merge-input')).not.toBeInTheDocument();
    expect(screen.getByTestId('btn-manual-merge')).toBeInTheDocument();
  });

  it('handles JSON object values gracefully', () => {
    renderPanel([
      makeConflict({
        localValue: '{"quantity":10,"unit":"m2"}',
        remoteValue: '{"quantity":12,"unit":"m2"}',
      }),
    ]);
    expect(screen.getByTestId('value-local')).toHaveTextContent('{"quantity":10,"unit":"m2"}');
    expect(screen.getByTestId('value-remote')).toHaveTextContent('{"quantity":12,"unit":"m2"}');
  });

  beforeEach(() => {
    vi.clearAllMocks();
  });
});
