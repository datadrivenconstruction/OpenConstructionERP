// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { floatingPref } from '@/shared/lib/floatingPrefs';
import { useAuthStore } from '@/stores/useAuthStore';
import { FloatingChatButton } from '@/features/erp-chat/FloatingChatButton';
import { FloatingButtonsCard } from './FloatingButtonsCard';

beforeEach(() => {
  localStorage.clear();
  floatingPref.reset();
  useAuthStore.setState({ isAuthenticated: true, accessToken: 'x' });
});

describe('<FloatingButtonsCard>', () => {
  it('shows both buttons by default and stores a hidden one', () => {
    render(<FloatingButtonsCard />);
    const recent = screen.getByRole('switch', { name: 'Show the Recent pages button' });
    const assistant = screen.getByRole('switch', { name: 'Show the AI assistant button' });
    expect(recent.getAttribute('aria-checked')).toBe('true');
    expect(assistant.getAttribute('aria-checked')).toBe('true');
    fireEvent.click(assistant);
    expect(floatingPref.read()).toEqual({ recent: false, assistant: true });
    expect(assistant.getAttribute('aria-checked')).toBe('false');
    fireEvent.click(assistant);
    expect(floatingPref.read()).toEqual({ recent: false, assistant: false });
  });
});

describe('the assistant button', () => {
  const renderButton = () =>
    render(
      <MemoryRouter initialEntries={['/boq']}>
        <FloatingChatButton />
      </MemoryRouter>,
    );

  it('is there by default and gone once hidden', () => {
    const { unmount } = renderButton();
    expect(screen.queryByTestId('floating-chat-button')).not.toBeNull();
    unmount();
    floatingPref.write({ recent: false, assistant: true });
    renderButton();
    expect(screen.queryByTestId('floating-chat-button')).toBeNull();
  });
});
