import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { StudioHomePage } from './StudioHomePage';

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(),
}));

import { apiGet } from '@/shared/lib/api';

function renderHome() {
  return render(
    <MemoryRouter>
      <StudioHomePage />
    </MemoryRouter>,
  );
}

describe('StudioHomePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the ACAP Studio heading and one project row with a Buka Studio link', async () => {
    (apiGet as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: 'p1', name: 'Rumah A' },
    ]);

    renderHome();

    expect(screen.getByText('ACAP Studio')).toBeInTheDocument();
    expect(
      screen.getByText('Dari gambar denah ke RAB, timeline, 3D & interior — terpandu.'),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Rumah A')).toBeInTheDocument();
    });

    const link = screen.getByRole('link', { name: 'Buka Studio' });
    expect(link).toHaveAttribute('href', '/projects/p1/studio');
  });

  it('shows the empty state when there are no projects', async () => {
    (apiGet as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    renderHome();

    await waitFor(() => {
      expect(screen.getByText(/belum ada project/i)).toBeInTheDocument();
    });
  });

  it('renders a "+ Project Baru" link to /projects/new', async () => {
    (apiGet as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    renderHome();

    expect(screen.getByRole('link', { name: /\+ project baru/i })).toHaveAttribute(
      'href',
      '/projects/new',
    );
  });
});