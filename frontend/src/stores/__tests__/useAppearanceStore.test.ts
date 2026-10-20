// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it } from 'vitest';
import { PLATFORM_APPEARANCE, USER_APPEARANCE_KEY, WORKSPACE_APPEARANCE_KEY } from '@/shared/lib/appearance';
import { useAppearanceStore } from '../useAppearanceStore';

const html = () => document.documentElement.dataset;

beforeEach(() => {
  localStorage.clear();
  useAppearanceStore.getState().followWorkspace();
  useAppearanceStore.getState().setWorkspaceDefault(null);
});

describe('useAppearanceStore', () => {
  it('a user with no choice follows the workspace default', () => {
    useAppearanceStore.getState().setWorkspaceDefault({ accent: 'emerald', radius: 'sharp' });
    const s = useAppearanceStore.getState();
    expect(s.user).toBeNull();
    expect(s.effective).toEqual({ ...PLATFORM_APPEARANCE, accent: 'emerald', radius: 'sharp' });
    expect(html().accent).toBe('emerald');
    expect(JSON.parse(localStorage.getItem(WORKSPACE_APPEARANCE_KEY)!)).toEqual({ accent: 'emerald', radius: 'sharp' });
  });

  it('a personal choice overrides the workspace and persists', () => {
    useAppearanceStore.getState().setWorkspaceDefault({ accent: 'emerald' });
    useAppearanceStore.getState().setAxis('accent', 'crimson');
    const s = useAppearanceStore.getState();
    expect(s.effective.accent).toBe('crimson');
    expect(html().accent).toBe('crimson');
    expect(JSON.parse(localStorage.getItem(USER_APPEARANCE_KEY)!).accent).toBe('crimson');
  });

  it('"use workspace default" drops the override', () => {
    useAppearanceStore.getState().setWorkspaceDefault({ density: 'compact' });
    useAppearanceStore.getState().setAppearance({ ...PLATFORM_APPEARANCE, accent: 'amber' });
    useAppearanceStore.getState().followWorkspace();
    const s = useAppearanceStore.getState();
    expect(s.user).toBeNull();
    expect(s.effective).toEqual({ ...PLATFORM_APPEARANCE, density: 'compact' });
    expect(localStorage.getItem(USER_APPEARANCE_KEY)).toBeNull();
    expect(html().density).toBe('compact');
  });

  it('rejects a workspace default with values it does not know', () => {
    useAppearanceStore.getState().setWorkspaceDefault({ accent: 'pink', font: 'inter' });
    expect(useAppearanceStore.getState().workspace).toEqual({ font: 'inter' });
  });
});
