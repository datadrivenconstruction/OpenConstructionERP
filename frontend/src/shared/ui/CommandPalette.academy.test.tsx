// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Courses and guides in the palette: only for a typed query, at most three
 * rows, and a row opens the Academy through the desktop-aware opener.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/features/projects/api', () => ({ projectsApi: { list: () => Promise.resolve([]) } }));
vi.mock('@/features/boq/api', () => ({ boqApi: { list: () => Promise.resolve([]) } }));
vi.mock('@/shared/lib/api', () => ({ apiGet: () => Promise.resolve({ hits: [] }) }));
const openLink = vi.fn();
vi.mock('@/shared/lib/desktop', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/desktop')>()),
  openLink: (url: string) => openLink(url),
}));

import { CommandPalette } from './CommandPalette';

const academyRows = () => [...document.querySelectorAll('[data-testid^="palette-row-academy-"]')];

function renderPalette() {
  render(
    <MemoryRouter>
      <CommandPalette open onClose={vi.fn()} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  openLink.mockClear();
});

describe('CommandPalette courses and guides', () => {
  it('shows no academy group on an empty or one-letter query', async () => {
    renderPalette();
    expect(academyRows()).toHaveLength(0);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'c' } });
    expect(academyRows()).toHaveLength(0);
  });

  it('finds the BIM course for "clash" and opens it with openLink', async () => {
    renderPalette();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'clash' } });
    const row = await screen.findByTestId('palette-row-academy-course:ashbrook-bim-clash-detection');
    fireEvent.click(row.querySelector('button')!);
    expect(openLink).toHaveBeenCalledWith(expect.stringContaining('openconstructionacademy.com/courses/ashbrook-bim-clash-detection'));
  });

  it('lists at most three rows and marks a paid one for assistive technology', async () => {
    renderPalette();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'cost' } });
    await waitFor(() => expect(academyRows().length).toBeGreaterThan(0));
    const rows = academyRows();
    expect(rows.length).toBeLessThanOrEqual(3);
    rows.forEach((row) => {
      const button = row.querySelector('button')!;
      const paid = row.querySelector('svg.lucide-crown') !== null;
      expect(button.getAttribute('aria-description') !== null).toBe(paid);
    });
  });
});
