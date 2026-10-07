// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/react';

// Exercise the real page boundary, not the unused ChatTopBar. Resizable
// panels have no layout in jsdom; conversation data must not control identity.
const state = vi.hoisted(() => ({ aiConfigured: true as boolean | null, isStreaming: false, mobile: false }));
vi.mock('../useFloatingChat', () => ({ useIsMobileViewport: () => state.mobile }));
vi.mock('react-resizable-panels', () => ({
  Group: ({ children, orientation, onLayoutChanged, defaultLayout }: {
    children: ReactNode;
    orientation: string;
    onLayoutChanged?: (layout: Record<string, number>, meta: { isUserInteraction: boolean }) => void;
    defaultLayout?: Record<string, number>;
  }) => <div data-testid="chat-panels" data-orientation={orientation} data-layout={JSON.stringify(defaultLayout)}>
    {children}
    <button onClick={() => onLayoutChanged?.({ 'chat-left': 45, 'chat-right': 55 }, { isUserInteraction: true })}>Resize panels</button>
  </div>,
  Panel: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Separator: () => null,
}));
vi.mock('../full-page/useChatFullPage', () => ({ useChatFullPage: () => ({ ...state }) }));
vi.mock('../full-page/left/ChatLeftPanel', () => ({ default: () => <input aria-label="Conversation" /> }));
vi.mock('../full-page/right/DataRightPanel', () => ({ default: () => <div>Data</div> }));
vi.mock('../full-page/AIConfigBanner', () => ({ default: () => null }));

import ChatFullPage from '../full-page/ChatFullPage';

afterEach(() => {
  cleanup();
  state.mobile = false;
  localStorage.removeItem('chat-panel-sizes');
});

describe('full-page AI identity', () => {
  it.each([true, false, null])('is visible before interaction, regardless of readiness: %s', (ready) => {
    state.aiConfigured = ready;
    const page = render(<ChatFullPage />);
    expect(page.getByTestId('chat-ai-disclosure')).toBeVisible();
    expect(page.getByTestId('chat-ai-disclosure')).toHaveTextContent('AI assistant');
  });

  it('does not disappear during streaming or become editable', () => {
    state.isStreaming = true;
    const page = render(<ChatFullPage />);
    const disclosure = page.getByTestId('chat-ai-disclosure');
    expect(disclosure).toBeVisible();
    expect(disclosure.closest('input, textarea, [contenteditable="true"]')).toBeNull();
    state.isStreaming = false;
    page.rerender(<ChatFullPage />);
    expect(disclosure).toBeVisible();
  });
});

it('stacks narrow-screen panels without replacing the saved desktop split', () => {
  const desktop = { 'chat-left': 35, 'chat-right': 65 };
  localStorage.setItem('chat-panel-sizes', JSON.stringify(desktop));
  state.mobile = true;
  const page = render(<ChatFullPage />);
  fireEvent.change(page.getByLabelText('Conversation'), { target: { value: 'Unsent draft' } });
  expect(page.getByTestId('chat-panels')).toHaveAttribute('data-orientation', 'vertical');
  expect(page.getByTestId('chat-panels')).not.toHaveAttribute('data-layout');
  fireEvent.click(page.getByText('Resize panels'));
  expect(JSON.parse(localStorage.getItem('chat-panel-sizes')!)).toEqual(desktop);
  state.mobile = false;
  page.rerender(<ChatFullPage />);
  expect(page.getByLabelText('Conversation')).toHaveValue('Unsent draft');
  expect(page.getByTestId('chat-panels')).toHaveAttribute('data-orientation', 'horizontal');
  expect(page.getByTestId('chat-panels')).toHaveAttribute('data-layout', JSON.stringify(desktop));
  fireEvent.click(page.getByText('Resize panels'));
  expect(JSON.parse(localStorage.getItem('chat-panel-sizes')!)).toEqual({ 'chat-left': 45, 'chat-right': 55 });
});

it.each([
  {},
  { oldLeft: 35, oldRight: 65 },
  { 'chat-left': '35', 'chat-right': 65 },
  { 'chat-left': -10, 'chat-right': 110 },
  { 'chat-left': 35, 'chat-right': 35 },
  { 'chat-left': 35, 'chat-right': null },
])('ignores an invalid or obsolete saved split: %j', (layout) => {
  localStorage.setItem('chat-panel-sizes', JSON.stringify(layout));
  const page = render(<ChatFullPage />);
  expect(page.getByTestId('chat-panels')).not.toHaveAttribute('data-layout');
  expect(page.getByLabelText('Conversation')).toBeVisible();
});
