// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { DemoScopeNotice } from './DemoScopeNotice';
import type { DemoScope } from '@/shared/lib/useDemoScope';

function scope(over: Partial<DemoScope>): DemoScope {
  return {
    demoMode: true,
    profile: null,
    project: { id: 'london', name: 'Halesworth House' },
    projectId: 'london',
    showAll: false,
    setShowAll: vi.fn(),
    ...over,
  };
}

describe('DemoScopeNotice', () => {
  it('says the list is the open demo only, and offers every demo project', () => {
    const s = scope({});
    render(<DemoScopeNotice scope={s} />);
    expect(screen.getByTestId('demo-scope-notice').getAttribute('data-scope')).toBe('demo');
    expect(screen.getByTestId('demo-scope-notice').textContent).toContain('Halesworth House');
    fireEvent.click(screen.getByTestId('demo-scope-toggle'));
    expect(s.setShowAll).toHaveBeenCalledWith(true);
  });

  it('offers the way back once every project is shown', () => {
    const s = scope({ projectId: null, showAll: true });
    render(<DemoScopeNotice scope={s} />);
    expect(screen.getByTestId('demo-scope-notice').getAttribute('data-scope')).toBe('all');
    fireEvent.click(screen.getByTestId('demo-scope-toggle'));
    expect(s.setShowAll).toHaveBeenCalledWith(false);
  });

  it('renders nothing outside a demo', () => {
    const { container } = render(<DemoScopeNotice scope={scope({ demoMode: false })} />);
    expect(container.innerHTML).toBe('');
  });
});
