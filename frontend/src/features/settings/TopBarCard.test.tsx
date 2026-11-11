import { render, screen, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { TopBarCard } from './TopBarCard';
import { TOP_BAR_PREFS_KEY, resetTopBarPrefsCache, readTopBarPrefs } from '@/shared/lib/topBarPrefs';

describe('TopBarCard', () => {
  beforeEach(() => {
    localStorage.clear();
    resetTopBarPrefsCache();
  });

  it('shows every item by default', () => {
    render(<TopBarCard />);
    expect(screen.getByTestId('topbar-switch-search').getAttribute('aria-checked')).toBe('true');
    expect(screen.getByTestId('topbar-preview-search')).toBeTruthy();
  });

  it('hides an item, updates the preview and persists the choice', () => {
    render(<TopBarCard />);
    fireEvent.click(screen.getByTestId('topbar-switch-search'));
    expect(screen.getByTestId('topbar-switch-search').getAttribute('aria-checked')).toBe('false');
    expect(screen.queryByTestId('topbar-preview-search')).toBeNull();
    expect(readTopBarPrefs().search).toBe(true);
    expect(JSON.parse(localStorage.getItem(TOP_BAR_PREFS_KEY) ?? '{}').search).toBe(true);
  });
});
