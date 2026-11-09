// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MenuSizeCard } from './MenuSizeCard';
import { SidebarResizeHandle } from '@/app/layout/SidebarResizeHandle';
import { useSidebarPrefsStore } from '@/stores/useSidebarPrefsStore';

describe('MenuSizeCard', () => {
  beforeEach(() => {
    localStorage.clear();
    useSidebarPrefsStore.setState({ width: 248, labelMode: 'wrap' });
  });

  it('switches the label mode and shows it in the preview', () => {
    render(<MenuSizeCard />);
    const preview = screen.getByTestId('menu-size-preview');
    expect(preview.querySelector('.truncate')).toBeNull();
    fireEvent.click(screen.getByRole('radio', { name: /One line/ }));
    expect(useSidebarPrefsStore.getState().labelMode).toBe('single');
    expect(preview.querySelector('.truncate')).not.toBeNull();
    // The full name stays reachable in the tooltip.
    const titles = Array.from(preview.querySelectorAll('.truncate')).map((el) => el.getAttribute('title'));
    expect(titles.some((title) => /Bill of quantities/.test(title ?? ''))).toBe(true);
  });

  it('slider writes the width and Reset restores the default', () => {
    render(<MenuSizeCard />);
    const slider = screen.getByRole('slider');
    expect(slider.getAttribute('min')).toBe('200');
    expect(slider.getAttribute('max')).toBe('360');
    expect(slider.getAttribute('step')).toBe('8');
    fireEvent.change(slider, { target: { value: '320' } });
    expect(useSidebarPrefsStore.getState().width).toBe(320);
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
    expect(useSidebarPrefsStore.getState().width).toBe(248);
  });
});

describe('SidebarResizeHandle', () => {
  beforeEach(() => {
    localStorage.clear();
    useSidebarPrefsStore.setState({ width: 248, labelMode: 'wrap' });
  });

  it('is a keyboard separator that writes the shared width (LTR)', () => {
    render(<SidebarResizeHandle rtl={false} />);
    const handle = screen.getByRole('separator');
    expect(handle.getAttribute('aria-valuenow')).toBe('248');
    fireEvent.keyDown(handle, { key: 'ArrowRight' });
    expect(useSidebarPrefsStore.getState().width).toBe(256);
    fireEvent.keyDown(handle, { key: 'ArrowLeft', shiftKey: true });
    expect(useSidebarPrefsStore.getState().width).toBe(224);
    fireEvent.keyDown(handle, { key: 'End' });
    expect(useSidebarPrefsStore.getState().width).toBe(360);
  });

  it('mirrors the arrows in RTL', () => {
    render(<SidebarResizeHandle rtl />);
    const handle = screen.getByRole('separator');
    fireEvent.keyDown(handle, { key: 'ArrowLeft' });
    expect(useSidebarPrefsStore.getState().width).toBe(256);
    fireEvent.keyDown(handle, { key: 'ArrowRight' });
    expect(useSidebarPrefsStore.getState().width).toBe(248);
  });
});
