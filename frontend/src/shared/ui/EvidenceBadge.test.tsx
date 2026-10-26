import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EvidenceBadge } from './EvidenceBadge';
import type { PhotoEvidence } from '@/shared/lib/photoEvidence';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => (opts && 'meters' in opts ? `${key}:${opts.meters}` : key),
  }),
}));

const full: PhotoEvidence = {
  path: 'p',
  sha256: 'abcdef0123456789abcdef',
  size_bytes: 10,
  received_at: '2026-10-25T09:00:00Z',
  exif: {},
  device: null,
  location: { lat: 48.1, lon: 11.5, accuracy_m: 6, source: 'device' },
  captured_at: { value: '2026-10-25T09:00:00Z', source: 'device' },
  orientation: { heading_deg: 90 },
  grade: 'full',
};

describe('EvidenceBadge', () => {
  it('shows the accuracy on the compact badge', () => {
    render(<EvidenceBadge evidence={full} compact />);
    expect(screen.getByTestId('evidence-badge').textContent).toContain('field_evidence.accuracy_short');
  });

  it('lists location, time, heading and hash in the detail view', () => {
    render(<EvidenceBadge evidence={full} />);
    const details = screen.getByTestId('evidence-details');
    expect(details.textContent).toContain('field_evidence.grade_full');
    expect(details.textContent).toContain('field_evidence.heading');
    expect(details.textContent).toContain('SHA-256 abcdef0123456789');
  });

  it('says when a photo has no evidence', () => {
    render(<EvidenceBadge evidence={null} />);
    expect(screen.getByText('field_evidence.none')).toBeTruthy();
  });

  it('marks an unlocated photo as basic', () => {
    render(<EvidenceBadge evidence={{ ...full, location: null, grade: 'basic' }} />);
    expect(screen.getByTestId('evidence-details').textContent).toContain('field_evidence.no_location');
  });
});
