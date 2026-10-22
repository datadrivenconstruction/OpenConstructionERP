import { beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { useAppearanceStore } from '@/stores/useAppearanceStore';
import { AppearanceStyleCard } from './AppearanceStyleCard';

beforeEach(() => {
  localStorage.clear();
  useAppearanceStore.getState().followWorkspace();
});

describe('<AppearanceStyleCard> text size', () => {
  it('offers five sizes as a radiogroup and applies the pick to <html>', () => {
    render(<AppearanceStyleCard />);
    const group = within(screen.getByRole('radiogroup', { name: 'Text size' }));
    expect(group.getAllByRole('radio')).toHaveLength(5);
    const larger = group.getByRole('radio', { name: 'Larger, 125%' });
    expect(larger).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(larger);
    expect(larger).toHaveAttribute('aria-checked', 'true');
    expect(document.documentElement.dataset.text).toBe('larger');
    expect(JSON.parse(localStorage.getItem('oe_appearance_v1') ?? '{}').text).toBe('larger');
  });
});
