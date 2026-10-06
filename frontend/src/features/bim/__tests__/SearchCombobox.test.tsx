// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Enter in the search combobox. Typing used to highlight the first option at
 * once, so typing "Progetto" and pressing Enter searched for "Progetto
 * esecutivo" instead of what was typed. Now nothing is highlighted until
 * ArrowDown. Enter on a highlighted option picks it; Enter on text spelled
 * like an option takes that option and still runs Enter; anything else hands
 * the typed text on.
 */
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { SearchCombobox, type ComboOption } from '../SearchCombobox';

const OPTIONS: ComboOption[] = [
  { value: 'Progetto esecutivo', label: 'Progetto esecutivo' },
  { value: 'Progetto', label: 'Progetto' },
  { value: 'Stato di fatto', label: 'Stato di fatto' },
];

function Harness({ onSelect, onEnter }: { onSelect: (o: ComboOption) => void; onEnter: () => void }) {
  const [text, setText] = useState('');
  return (
    <SearchCombobox
      inputValue={text}
      onInputChange={setText}
      options={OPTIONS}
      onSelect={(o) => {
        setText(o.value);
        onSelect(o);
      }}
      onEnter={onEnter}
      ariaLabel="Value"
      testId="combo"
    />
  );
}

function setup() {
  const onSelect = vi.fn();
  const onEnter = vi.fn();
  render(<Harness onSelect={onSelect} onEnter={onEnter} />);
  const input = screen.getByTestId('combo');
  fireEvent.focus(input);
  return { input, onSelect, onEnter };
}

describe('SearchCombobox Enter', () => {
  it('uses the typed text when it only partly matches an option', () => {
    const { input, onSelect, onEnter } = setup();
    fireEvent.change(input, { target: { value: 'Proget' } });
    expect(input).not.toHaveAttribute('aria-activedescendant');
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSelect).not.toHaveBeenCalled();
    expect(onEnter).toHaveBeenCalledTimes(1);
    expect(input).toHaveValue('Proget');
  });

  it('takes the option spelled exactly like the typed text, not the first partial match, and carries on', () => {
    const { input, onSelect, onEnter } = setup();
    fireEvent.change(input, { target: { value: ' progetto ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSelect).toHaveBeenCalledWith(OPTIONS[1]);
    expect(onEnter).toHaveBeenCalledTimes(1);
    expect(input).toHaveValue('Progetto');
  });

  it('picks the option highlighted with ArrowDown', () => {
    const { input, onSelect, onEnter } = setup();
    fireEvent.change(input, { target: { value: 'Proget' } });
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSelect).toHaveBeenCalledWith(OPTIONS[1]);
    expect(onEnter).not.toHaveBeenCalled();
  });

  it('hands an empty input on to onEnter', () => {
    const { input, onSelect, onEnter } = setup();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSelect).not.toHaveBeenCalled();
    expect(onEnter).toHaveBeenCalledTimes(1);
  });
});
