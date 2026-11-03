import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const demo = vi.hoisted(() => ({ demoMode: true, loaded: true, size: 4 }));

vi.mock('@/shared/ui/DemoSwitcherBar', () => ({
  useDemoProjects: () => ({
    demoMode: demo.demoMode,
    loaded: demo.loaded,
    bySlug: { size: demo.size },
    open: () => {},
  }),
}));

import { DemoQuickStart } from './DemoQuickStart';
import { demoFaceFor } from '@/features/demo/DemoChooserPage';

function renderIt() {
  return render(
    <MemoryRouter>
      <DemoQuickStart />
    </MemoryRouter>,
  );
}

describe('DemoQuickStart', () => {
  it('renders six cards with a hex mark each and real counts', () => {
    renderIt();
    for (const id of ['what', 'data', 'try', 'roles', 'limits', 'install']) {
      expect(screen.getByTestId(`demo-quick-card-${id}`)).toBeTruthy();
    }
    expect(screen.getAllByTestId('hex-mark')).toHaveLength(6);
    expect(screen.getByTestId('demo-quick-card-data').textContent).toContain('4');
    const pricing = screen.getByTestId('demo-quick-card-install').querySelector('a');
    expect(pricing?.getAttribute('href')).toBe('https://openconstructionerp.com/pricing');
  });

  it('shows nothing outside demo mode', () => {
    demo.demoMode = false;
    const { container } = renderIt();
    expect(container.innerHTML).toBe('');
    demo.demoMode = true;
  });
});

describe('demoFaceFor', () => {
  it('gives every known demo a company photo and unknown slugs a drawing', () => {
    expect(demoFaceFor('contractor-jeddah').src).toMatch(/cmt-general-contractor\.webp$/);
    expect(demoFaceFor('nope')).toEqual({ src: null, kind: 'warehouse' });
  });
});
