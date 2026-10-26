// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** A proposal from an external MCP client says so in its row; the in-app assistant's do not. */
import { describe, expect, it } from 'vitest';
import type { TFunction } from 'i18next';
import { actionMetaLine } from '../ChangesView';
import { normalizeChatAction } from '../types';
import { buildActionListQuery } from '../api';
import { makeAction } from './fixtures';

const t = ((_key: string, opts?: Record<string, unknown>) =>
  String(opts?.defaultValue ?? '').replace(/\{\{(\w+)\}\}/g, (_m, k: string) => String(opts?.[k] ?? ''))) as unknown as TFunction;

describe('proposal source', () => {
  it('marks a proposal from an external client in the row meta line', () => {
    expect(actionMetaLine(makeAction({ source: 'mcp' }), t)).toContain('via external AI client');
    expect(actionMetaLine(makeAction({ source: 'chat' }), t)).not.toContain('via external AI client');
  });

  it('reads a missing source as the in-app assistant', () => {
    const { source: _drop, ...raw } = makeAction();
    expect(normalizeChatAction(raw as Record<string, unknown>).source).toBe('chat');
  });

  it('sends the source filter to the list endpoint', () => {
    expect(buildActionListQuery({ source: 'mcp', status: 'proposed' })).toContain('source=mcp');
  });
});
