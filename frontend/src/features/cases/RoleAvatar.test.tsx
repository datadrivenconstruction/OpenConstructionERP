// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Role avatars are photographs with the vector persona as the fallback.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      typeof opts?.defaultValue === 'string' ? opts.defaultValue : key,
    i18n: { language: 'en' },
  }),
}));

import { RoleAvatar } from './RoleAvatar';
import { RolePicker } from '../videos/RolePicker';
import { ROLE_META } from './roles';

afterEach(cleanup);

describe('RoleAvatar photos', () => {
  it('renders a lazy circular photo with the role name as alt', () => {
    render(<RoleAvatar role="estimator" />);
    const img = screen.getByRole('img', { name: 'Estimator' });
    expect(img.getAttribute('src')).toBe('/roles/estimator-96.webp');
    expect(img.getAttribute('srcset')).toContain('/roles/estimator-192.webp 2x');
    expect(img.getAttribute('loading')).toBe('lazy');
    expect(img.className).toContain('rounded-full');
    expect(img.className).toContain('dark:ring-white');
  });

  it('falls back to the vector persona when the photo fails', () => {
    const { container } = render(<RoleAvatar role="foreman" />);
    fireEvent.error(screen.getByRole('img', { name: 'Foreman / supervisor' }));
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('svg')).not.toBeNull();
  });

  it('the role picker shows one photo per role', () => {
    render(<RolePicker value={null} onPick={() => {}} />);
    expect(document.querySelectorAll('[data-testid="video-role-picker"] img')).toHaveLength(ROLE_META.length);
  });
});
