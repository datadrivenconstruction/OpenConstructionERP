// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPut: vi.fn() }));
vi.mock('@/shared/lib/api', () => api);
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_k: string, o?: { defaultValue?: string; [k: string]: unknown }) =>
      (o?.defaultValue ?? _k).replace(/\{\{(\w+)\}\}/g, (_m, v: string) => String(o?.[v] ?? '')),
  }),
}));

import { SidebarLayoutsPanel } from './SidebarLayoutsPanel';
import { sanitizeLayoutData, type SidebarLayoutData } from './sidebarLayouts';
import { useSidebarLayoutsStore } from './useSidebarLayoutsStore';

const current: SidebarLayoutData = { ...sanitizeLayoutData({}), hiddenModules: ['/rfi'] };

describe('SidebarLayoutsPanel', () => {
  beforeEach(() => {
    api.apiGet.mockReset();
    api.apiPut.mockReset();
    api.apiGet.mockResolvedValue({ layouts: [] });
    api.apiPut.mockImplementation(async (_p: string, body: unknown) => body);
    useSidebarLayoutsStore.getState().clear();
  });

  it('saves the current menu under a name and switches back to it', async () => {
    const onApply = vi.fn();
    render(<SidebarLayoutsPanel current={current} onApply={onApply} />);
    fireEvent.click(screen.getByRole('button', { name: /My layouts/ }));
    fireEvent.change(screen.getByLabelText('Layout name'), { target: { value: 'Site week' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save current' }));
    const row = await screen.findByRole('button', { name: 'Site week' });
    expect(row.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(row);
    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({ hiddenModules: ['/rfi'] }));
  });

  it('shows a message for an empty name and a duplicate', async () => {
    render(<SidebarLayoutsPanel current={current} onApply={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /My layouts/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Save current' }));
    expect((await screen.findByRole('alert')).textContent).toContain('Enter a name');
    fireEvent.change(screen.getByLabelText('Layout name'), { target: { value: 'A' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save current' }));
    await screen.findByRole('button', { name: 'A' });
    fireEvent.change(screen.getByLabelText('Layout name'), { target: { value: 'a' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save current' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('already have'));
  });

  it('renames and deletes after confirmation', async () => {
    api.apiGet.mockResolvedValue({ layouts: [{ id: 'x', name: 'Old', data: {} }] });
    render(<SidebarLayoutsPanel current={current} onApply={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /My layouts/ }));
    fireEvent.click(await screen.findByRole('button', { name: 'Rename "Old"' }));
    fireEvent.change(screen.getByLabelText('Rename "Old"'), { target: { value: 'New' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save name' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete "New"' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete layout' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'New' })).toBeNull());
  });
});
