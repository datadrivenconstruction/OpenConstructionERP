import { afterEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatusBar } from './StatusBar';
import { DEFAULT_CONVENTIONS } from '../units/conventions';
import { usePreferencesStore } from '@/stores/usePreferencesStore';

const props = {
  cursor: null, snap: null, snapOn: true, conventions: DEFAULT_CONVENTIONS, scale: 1329.6, csf: 0.99974593,
  crsName: 'Local', residualMm: null, selected: 0, dirty: false,
};

describe('StatusBar numbers', () => {
  afterEach(() => usePreferencesStore.setState({ numberLocale: 'auto' }));

  it('writes scale and CSF with the reader\u2019s separators', () => {
    usePreferencesStore.setState({ numberLocale: 'de-DE' });
    render(<StatusBar {...props} />);
    const bar = screen.getByTestId('plan-status-bar');
    expect(bar.textContent).toContain('1:1.330');
    expect(bar.textContent).toContain('0,99974593');
  });

  it('keeps the point for English', () => {
    usePreferencesStore.setState({ numberLocale: 'en-US' });
    render(<StatusBar {...props} />);
    expect(screen.getByTestId('plan-status-bar').textContent).toContain('1:1,330');
  });
});
