import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { LangtextEditor, type LangtextEditorProps } from './LangtextEditor';

const row = {
  id: 'p1',
  ordinal: '01.02.0030',
  description: 'Beton C25/30',
  metadata: { gaeb_long_text: 'Zeile 1\nZeile 2' },
  isSection: false,
};

function setup(over: Partial<LangtextEditorProps> = {}) {
  const props: LangtextEditorProps = {
    row,
    focus: 'long',
    readOnly: false,
    hasPrev: false,
    hasNext: true,
    onNavigate: vi.fn(),
    onSave: vi.fn(),
    onClose: vi.fn(),
    ...over,
  };
  render(<LangtextEditor {...props} />);
  const [short, long] = screen.getAllByRole('textbox') as HTMLTextAreaElement[];
  return { props, short: short!, long: long! };
}

describe('LangtextEditor', () => {
  it('shows both texts with their line breaks', () => {
    const { short, long } = setup();
    expect(short.value).toBe('Beton C25/30');
    expect(long.value).toBe('Zeile 1\nZeile 2');
  });

  it('saves Kurztext and Langtext together with the old values for undo', () => {
    const { props, long } = setup();
    fireEvent.change(long, { target: { value: 'Neu\r\nZweite Zeile ' } });
    fireEvent.keyDown(long, { key: 'Enter', ctrlKey: true });
    expect(props.onSave).toHaveBeenCalledWith(
      'p1',
      { description: 'Beton C25/30', long_text: 'Neu\nZweite Zeile' },
      { description: 'Beton C25/30', long_text: 'Zeile 1\nZeile 2' },
    );
    expect(props.onClose).toHaveBeenCalled();
  });

  it('closes without saving when nothing changed', () => {
    const { props, long } = setup();
    fireEvent.keyDown(long, { key: 'Enter', ctrlKey: true });
    expect(props.onSave).not.toHaveBeenCalled();
    expect(props.onClose).toHaveBeenCalled();
  });

  it('saves and moves to the next row on Alt+Down', () => {
    const { props, short } = setup();
    fireEvent.change(short, { target: { value: 'Beton C30/37' } });
    fireEvent.keyDown(short, { key: 'ArrowDown', altKey: true });
    expect(props.onSave).toHaveBeenCalledTimes(1);
    expect(props.onNavigate).toHaveBeenCalledWith(1);
  });

  it('warns when the Kurztext is longer than GAEB allows', () => {
    const { short } = setup();
    fireEvent.change(short, { target: { value: 'x'.repeat(71) } });
    expect(screen.getByText(/71 \/ 70/)).toBeTruthy();
  });

  it('never saves a read-only bill', () => {
    const { props, long } = setup({ readOnly: true });
    fireEvent.change(long, { target: { value: 'anders' } });
    fireEvent.keyDown(long, { key: 'Enter', ctrlKey: true });
    expect(props.onSave).not.toHaveBeenCalled();
  });
});
