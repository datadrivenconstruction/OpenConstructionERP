// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The CRS dialog must always let the user out: a viewer cannot save a system,
 * so a dialog without Cancel or Escape locked the whole survey page.
 */
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', async (orig) => ({
  ...(await orig<typeof import('./api')>()),
  searchCrs: vi.fn(async () => []),
  setProjectCrs: vi.fn(),
}));

const { CrsDialog } = await import('./CrsDialog');

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe('CrsDialog', () => {
  it('offers Cancel and closes on it when the project has no system yet', () => {
    const onClose = vi.fn();
    wrap(<CrsDialog open projectId="p1" state={{ crs: null, suggestions: [], point_count: 0 }} onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes on Escape when the project has no system yet', () => {
    const onClose = vi.fn();
    wrap(<CrsDialog open projectId="p1" state={{ crs: null, suggestions: [], point_count: 0 }} onClose={onClose} />);
    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});
