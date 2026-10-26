// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { gChordPref } from '@/shared/lib/gChords';
import { useKeyboardShortcuts } from '@/shared/hooks/useKeyboardShortcuts';
import { ChordShortcutsCard } from './ChordShortcutsCard';

function Where() {
  useKeyboardShortcuts({ onOpenSearch: () => {}, onToggleShortcutsDialog: () => {} });
  return <span data-testid="where">{useLocation().pathname}</span>;
}

beforeEach(() => {
  localStorage.clear();
  gChordPref.reset();
});

const press = (key: string) => fireEvent.keyDown(document.body, { key });

describe('<ChordShortcutsCard>', () => {
  it('lists every chord with its default key and nothing to reset', () => {
    render(<ChordShortcutsCard />);
    expect((screen.getByLabelText('Key after G for Bills of quantities') as HTMLInputElement).value).toBe('B');
    expect((screen.getByRole('button', { name: 'Reset all shortcuts' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('remaps a chord, and the global G handler follows it at once', () => {
    render(
      <MemoryRouter initialEntries={['/start']}>
        <Where />
        <ChordShortcutsCard />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText('Key after G for Bills of quantities'), { target: { value: 'BX' } });
    expect(gChordPref.read()).toEqual({ boq: 'x' });
    press('g');
    press('b');
    expect(screen.getByTestId('where').textContent).toBe('/start');
    press('g');
    press('x');
    expect(screen.getByTestId('where').textContent).toBe('/boq');
  });

  it('refuses a key that is taken and says which page has it', () => {
    render(<ChordShortcutsCard />);
    fireEvent.change(screen.getByLabelText('Key after G for Bills of quantities'), { target: { value: 'BP' } });
    expect(gChordPref.read()).toEqual({});
    expect(screen.getByRole('alert').textContent).toContain('P is already used for');
  });

  it('resets one chord and all of them', () => {
    gChordPref.write({ boq: 'x', finance: 'z' });
    render(<ChordShortcutsCard />);
    fireEvent.click(screen.getByRole('button', { name: 'Reset Bills of quantities to B' }));
    expect(gChordPref.read()).toEqual({ finance: 'z' });
    fireEvent.click(screen.getByRole('button', { name: 'Reset all shortcuts' }));
    expect(gChordPref.read()).toEqual({});
  });
});
