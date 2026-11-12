// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// The letter editor: chips insert a field where the cursor is, the rules the
// server runs on save show while typing, and a read-only editor offers no chips.
// The i18n mock in src/test/setup.ts returns the defaultValue.

import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { LetterTextEditor } from './LetterTextEditor';
import { checkLetterText, insertPlaceholder, placeholdersIn, type LetterPlaceholder, type LetterText } from './letterRules';

const PLACEHOLDERS: LetterPlaceholder[] = [
  { name: 'bidder', sample: 'Example Builders Ltd', required: false },
  { name: 'package', sample: 'Concrete works', required: true },
  { name: 'amount', sample: '1,284,500.00 EUR', required: true },
];

const TEXT: LetterText = {
  subject: 'Award: {package}',
  heading: 'Notification',
  body: 'Dear {bidder},\n\nWe award {package} for {amount}.',
  closing: 'Yours faithfully,',
};

function Harness({ initial, onChange }: { initial: LetterText; onChange?: (v: LetterText) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <LetterTextEditor
      value={value}
      placeholders={PLACEHOLDERS}
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
    />
  );
}

describe('letter rules', () => {
  it('finds placeholders once each, in order', () => {
    expect(placeholdersIn('{a} {b} {a} {0} {}')).toEqual(['a', 'b']);
  });

  it('accepts a complete letter', () => {
    expect(checkLetterText(TEXT, PLACEHOLDERS)).toEqual([]);
  });

  it('reports an empty body and an unknown field as errors, a missing amount as a warning', () => {
    const issues = checkLetterText({ ...TEXT, body: ' ', subject: '{bonus} {package}' }, PLACEHOLDERS);
    expect(issues.map((i) => [i.code, i.severity, i.placeholder])).toEqual([
      ['empty_body', 'error', ''],
      ['unknown_placeholder', 'error', 'bonus'],
      ['missing_required', 'warning', 'amount'],
    ]);
  });

  it('inserts at the selection, replacing selected text', () => {
    expect(insertPlaceholder('Dear X,', 5, 6, 'bidder')).toEqual({ value: 'Dear {bidder},', caret: 13 });
  });
});

describe('LetterTextEditor', () => {
  it('inserts a chip into the field last focused, at the cursor', () => {
    const onChange = vi.fn();
    render(<Harness initial={{ ...TEXT, heading: 'For ' }} onChange={onChange} />);
    const heading = screen.getByTestId('letter-field-heading') as HTMLInputElement;
    fireEvent.focus(heading);
    heading.setSelectionRange(4, 4);
    fireEvent.click(screen.getByTestId('letter-chip-package'));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ heading: 'For {package}' }));
  });

  it('shows the rule findings while typing', () => {
    render(<Harness initial={TEXT} />);
    expect(screen.queryByTestId('letter-issues')).toBeNull();
    fireEvent.change(screen.getByTestId('letter-field-body'), { target: { value: 'We award {package} {nope}.' } });
    const issues = screen.getByTestId('letter-issues');
    expect(issues.textContent).toContain('{nope} is not a field of this letter');
    expect(issues.textContent).toContain('{amount}');
  });

  it('offers no chips when read-only', () => {
    render(<LetterTextEditor value={TEXT} placeholders={PLACEHOLDERS} onChange={() => {}} readOnly />);
    expect(screen.queryByTestId('letter-chip-package')).toBeNull();
    expect((screen.getByTestId('letter-field-body') as HTMLTextAreaElement).readOnly).toBe(true);
  });
});
