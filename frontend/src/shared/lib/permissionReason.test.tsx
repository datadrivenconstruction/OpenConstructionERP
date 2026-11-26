// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, renderHook, screen } from '@testing-library/react';
import { Button } from '@/shared/ui/Button';
import { useAuthStore } from '@/stores/useAuthStore';
import { roleAtLeast, usePermissionReason, useRoleReason } from './permissionReason';

describe('usePermissionReason', () => {
  it('names who can act when the role falls short, and nothing when it passes', () => {
    useAuthStore.setState({ userRole: 'viewer' } as never);
    const viewer = renderHook(() => usePermissionReason('contracts.delete'));
    expect(viewer.result.current).toBe('Only a manager or administrator can do this.');

    useAuthStore.setState({ userRole: 'manager' } as never);
    const manager = renderHook(() => usePermissionReason('contracts.delete'));
    expect(manager.result.current).toBeUndefined();
  });

  it('words an editor-level gate for editors', () => {
    useAuthStore.setState({ userRole: 'viewer' } as never);
    const { result } = renderHook(() => usePermissionReason('contracts.update'));
    expect(result.current).toBe('Only an editor, manager or administrator can do this.');
  });
});

describe('useRoleReason and roleAtLeast', () => {
  it('follows a page-level flag', () => {
    expect(renderHook(() => useRoleReason(true, 'admin')).result.current).toBeUndefined();
    expect(renderHook(() => useRoleReason(false, 'admin')).result.current).toBe('Only an administrator can do this.');
  });

  it('resolves aliases and refuses unknown roles', () => {
    expect(roleAtLeast('estimator', 'editor')).toBe(true);
    expect(roleAtLeast('readonly', 'editor')).toBe(false);
    expect(roleAtLeast('stranger', 'editor')).toBe(false);
    expect(roleAtLeast('owner', 'admin')).toBe(true);
  });
});

describe('Button disabledReason', () => {
  it('stays on screen, disabled, with the reason as its tooltip, and ignores clicks', () => {
    const onClick = vi.fn();
    render(
      <Button disabledReason="Only a manager or administrator can do this." onClick={onClick}>
        Approve
      </Button>,
    );
    const button = screen.getByRole('button', { name: 'Approve' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-disabled', 'true');
    expect(button).toHaveAttribute('title', 'Only a manager or administrator can do this.');
    // The pointer must reach the button, or the tooltip never shows.
    expect(button.className).not.toContain('pointer-events-none');
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('behaves as a normal button when there is no reason', () => {
    const onClick = vi.fn();
    render(
      <Button disabledReason={undefined} title="Approve the change" onClick={onClick}>
        Approve
      </Button>,
    );
    const button = screen.getByRole('button', { name: 'Approve' });
    expect(button).toBeEnabled();
    expect(button).toHaveAttribute('title', 'Approve the change');
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledOnce();
  });
});
