// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The legend that explains the language tags on dashboard tiles. A tag alone
 * is a tooltip a phone never shows, so the note must be on screen whenever at
 * least one tile is not in the reader's language, and absent otherwise.
 *
 * Run: npx vitest run src/features/dashboard/__tests__/ContentLanguageNote.test.tsx
 */

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { ContentLanguageNote } from '../ContentLanguageNote';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
  }),
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

describe('ContentLanguageNote', () => {
  it('prints nothing when every tile is in the UI language', () => {
    const { container } = render(<ContentLanguageNote tags={[null, null]} />);
    expect(container.firstChild).toBeNull();
  });

  it('names each fallback language once and says why', () => {
    render(<ContentLanguageNote tags={[null, 'EN', 'EN', 'DE']} />);
    const note = screen.getByTestId('content-language-note');
    expect(note.textContent).toBe('ENDENot yet available in your language');
  });
});
