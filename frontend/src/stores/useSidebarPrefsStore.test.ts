// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it, vi } from 'vitest';

const KEY = 'oe_sidebar_prefs';

async function freshStore() {
  vi.resetModules();
  return import('./useSidebarPrefsStore');
}

describe('useSidebarPrefsStore', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.style.removeProperty('--oe-sidebar-width');
  });

  it('defaults keep today\'s menu: 248 px, wrapped names', async () => {
    const { useSidebarPrefsStore, SIDEBAR_DEFAULT_WIDTH } = await freshStore();
    expect(useSidebarPrefsStore.getState().width).toBe(SIDEBAR_DEFAULT_WIDTH);
    expect(useSidebarPrefsStore.getState().width).toBe(248);
    expect(useSidebarPrefsStore.getState().labelMode).toBe('wrap');
    expect(document.documentElement.style.getPropertyValue('--oe-sidebar-width')).toBe('');
  });

  it('clamps to 200-360 and snaps to steps of 8', async () => {
    const { useSidebarPrefsStore, normalizeSidebarWidth } = await freshStore();
    useSidebarPrefsStore.getState().setWidth(100);
    expect(useSidebarPrefsStore.getState().width).toBe(200);
    useSidebarPrefsStore.getState().setWidth(999);
    expect(useSidebarPrefsStore.getState().width).toBe(360);
    useSidebarPrefsStore.getState().setWidth(251);
    expect(useSidebarPrefsStore.getState().width).toBe(248);
    useSidebarPrefsStore.getState().setWidth(253);
    expect(useSidebarPrefsStore.getState().width).toBe(256);
    expect(normalizeSidebarWidth('wide')).toBe(248);
    expect(normalizeSidebarWidth(Number.NaN)).toBe(248);
  });

  it('persists and restores both preferences', async () => {
    let mod = await freshStore();
    mod.useSidebarPrefsStore.getState().setWidth(296);
    mod.useSidebarPrefsStore.getState().setLabelMode('single');
    expect(JSON.parse(localStorage.getItem(KEY) ?? '{}')).toEqual({ width: 296, labelMode: 'single' });

    mod = await freshStore();
    expect(mod.useSidebarPrefsStore.getState().width).toBe(296);
    expect(mod.useSidebarPrefsStore.getState().labelMode).toBe('single');
    // The saved width is on the page before the sidebar mounts: no layout jump.
    expect(document.documentElement.style.getPropertyValue('--oe-sidebar-width')).toBe('296px');
  });

  it('leaves the icon-only width alone at start', async () => {
    localStorage.setItem(KEY, JSON.stringify({ width: 312, labelMode: 'wrap' }));
    localStorage.setItem('oe_sidebar_iconified', '1');
    await freshStore();
    expect(document.documentElement.style.getPropertyValue('--oe-sidebar-width')).toBe('');
  });

  it('reset puts the width back and keeps the label mode', async () => {
    const { useSidebarPrefsStore } = await freshStore();
    useSidebarPrefsStore.getState().setLabelMode('single');
    useSidebarPrefsStore.getState().setWidth(344);
    useSidebarPrefsStore.getState().resetWidth();
    expect(useSidebarPrefsStore.getState().width).toBe(248);
    expect(useSidebarPrefsStore.getState().labelMode).toBe('single');
  });

  it('survives corrupt storage and unknown label modes', async () => {
    localStorage.setItem(KEY, '{not json');
    let mod = await freshStore();
    expect(mod.useSidebarPrefsStore.getState().width).toBe(248);
    localStorage.setItem(KEY, JSON.stringify({ width: 9000, labelMode: 'tiny' }));
    mod = await freshStore();
    expect(mod.useSidebarPrefsStore.getState().width).toBe(360);
    expect(mod.useSidebarPrefsStore.getState().labelMode).toBe('wrap');
  });
});
