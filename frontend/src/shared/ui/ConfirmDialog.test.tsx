import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ConfirmDialog } from './ConfirmDialog';

const defaultProps = {
  open: true,
  onConfirm: vi.fn(),
  onCancel: vi.fn(),
  title: 'Delete project?',
  message: 'This action cannot be undone.',
};

function renderDialog(overrides: Partial<typeof defaultProps> = {}) {
  const props = { ...defaultProps, ...overrides };
  return render(<ConfirmDialog {...props} />);
}

describe('ConfirmDialog', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders when open=true', () => {
    renderDialog();
    expect(screen.getByText('Delete project?')).toBeInTheDocument();
    expect(screen.getByText('This action cannot be undone.')).toBeInTheDocument();
  });

  it('hidden when open=false', () => {
    renderDialog({ open: false });
    expect(screen.queryByText('Delete project?')).not.toBeInTheDocument();
  });

  it('calls onConfirm when confirm clicked', () => {
    const onConfirm = vi.fn();
    renderDialog({ onConfirm });
    fireEvent.click(screen.getByTestId('confirm-dialog-confirm'));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('calls onCancel when cancel clicked', () => {
    const onCancel = vi.fn();
    renderDialog({ onCancel });
    // The cancel button uses the default label "Cancel" (from the i18n mock defaultValue)
    fireEvent.click(screen.getByText('Cancel'));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('calls onCancel on Escape', () => {
    const onCancel = vi.fn();
    renderDialog({ onCancel });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('shows custom labels', () => {
    renderDialog({
      onConfirm: vi.fn(),
      onCancel: vi.fn(),
      confirmLabel: 'Remove forever',
      cancelLabel: 'Keep it',
    } as Record<string, unknown>);
    expect(screen.getByText('Remove forever')).toBeInTheDocument();
    expect(screen.getByText('Keep it')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    renderDialog({ loading: true } as Record<string, unknown>);
    // The confirm button should be disabled when loading
    const confirmBtn = screen.getByTestId('confirm-dialog-confirm');
    expect(confirmBtn).toBeDisabled();
    // The cancel button should also be disabled
    expect(screen.getByText('Cancel')).toBeDisabled();
  });
});
