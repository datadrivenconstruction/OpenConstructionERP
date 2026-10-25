// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Test helper for the export menu's document-language list: opens the list of
// the menu whose main button has `testId` and picks the language shown under
// `name` (its own name, e.g. "Türkçe"). The menu itself must already be open.

import { fireEvent, screen } from '@testing-library/react';

export function pickDocumentLanguage(testId: string, name: string): void {
  // jsdom has no layout, so the list cannot scroll a row into view.
  if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => {};
  fireEvent.click(screen.getByTestId(`${testId}-lang`));
  const option = screen.getAllByRole('option').find((o) => o.textContent?.includes(name));
  if (!option) throw new Error(`No document language named ${name} in the list`);
  fireEvent.click(option);
}
