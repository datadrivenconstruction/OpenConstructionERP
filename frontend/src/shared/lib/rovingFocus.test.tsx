// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { onRadioGroupKeyDown, rovingTabIndex } from '@/shared/lib/rovingFocus';

function Grid() {
  const [sel, setSel] = useState<string | null>(null);
  const items = ['a', 'b', 'c'];
  return (
    <div role="radiogroup" aria-label="Countries" onKeyDown={onRadioGroupKeyDown}>
      {items.map((k, i) => (
        <button
          key={k}
          type="button"
          role="radio"
          aria-checked={sel === k}
          tabIndex={rovingTabIndex(sel === k, i, sel !== null)}
          onClick={() => setSel(k)}
        >
          {k}
        </button>
      ))}
    </div>
  );
}

describe('a choice grid with roving focus', () => {
  it('is one Tab stop and the arrows move and select', () => {
    render(<Grid />);
    const radios = screen.getAllByRole('radio');
    expect(radios.map((r) => r.tabIndex)).toEqual([0, -1, -1]);
    radios[0]!.focus();
    fireEvent.keyDown(radios[0]!, { key: 'ArrowRight' });
    expect(document.activeElement).toBe(radios[1]);
    expect(radios[1]!.getAttribute('aria-checked')).toBe('true');
    expect(radios.map((r) => r.tabIndex)).toEqual([-1, 0, -1]);
    fireEvent.keyDown(radios[1]!, { key: 'End' });
    expect(document.activeElement).toBe(radios[2]);
    fireEvent.keyDown(radios[2]!, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(radios[0]);
  });
});
