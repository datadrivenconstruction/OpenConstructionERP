// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render } from '@testing-library/react';

// Exercise the real page boundary, not the unused ChatTopBar. Resizable
// panels have no layout in jsdom; conversation data must not control identity.
const state = vi.hoisted(() => ({ aiConfigured: true as boolean | null, isStreaming: false }));
vi.mock('react-resizable-panels', () => ({
  Group: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Panel: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Separator: () => null,
}));
vi.mock('../full-page/useChatFullPage', () => ({ useChatFullPage: () => ({ ...state }) }));
vi.mock('../full-page/left/ChatLeftPanel', () => ({ default: () => <div>Conversation</div> }));
vi.mock('../full-page/right/DataRightPanel', () => ({ default: () => <div>Data</div> }));
vi.mock('../full-page/AIConfigBanner', () => ({ default: () => null }));

import ChatFullPage from '../full-page/ChatFullPage';

afterEach(cleanup);

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
