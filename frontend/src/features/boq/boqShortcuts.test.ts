// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The BOQ editor's keyboard shortcuts, decided by `resolveBoqShortcut`.
 *
 * The case that matters: on Windows AltGr arrives as Ctrl+Alt, and on
 * Croatian and German keyboards the euro sign is AltGr+E. Typing "12,50 €"
 * into a price cell used to start the Excel export and drop the euro sign.
 */
import { describe, it, expect, afterEach } from 'vitest';

import {
  isAltOrAltGraph,
  isCommandChord,
  isTextEntryElement,
  resolveBoqShortcut,
  type BoqShortcutKey,
} from './boqShortcuts';

const idle = { isEditing: false, hasSelection: false };
const editing = { isEditing: true, hasSelection: false };

/** Ctrl+<letter> as Windows reports it for a plain Ctrl chord. */
function ctrl(letter: string, extra: Partial<BoqShortcutKey> = {}): BoqShortcutKey {
  return {
    key: letter,
    code: `Key${letter.toUpperCase()}`,
    ctrlKey: true,
    altKey: false,
    shiftKey: false,
    metaKey: false,
    ...extra,
  };
}

/** AltGr+<physical key> producing `char`, as Windows reports it: Ctrl+Alt. */
function altGr(code: string, char: string): BoqShortcutKey {
  return {
    key: char,
    code,
    ctrlKey: true,
    altKey: true,
    shiftKey: false,
    metaKey: false,
    getModifierState: (k: string) => k === 'AltGraph' || k === 'Control' || k === 'Alt',
  };
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe('AltGr characters are text, never shortcuts', () => {
  it('AltGr+E (the euro sign on hr / de) does not start the export', () => {
    expect(resolveBoqShortcut(altGr('KeyE', '€'), idle)).toBeNull();
    expect(resolveBoqShortcut(altGr('KeyE', '€'), editing)).toBeNull();
  });

  it.each([
    ['KeyV', '@', 'hr at sign vs paste / import chords'],
    ['KeyL', 'Ł', 'hr L-stroke vs Ctrl+L lock'],
    ['KeyI', 'í', 'accented i vs Ctrl+I import'],
    ['KeyD', 'đ', 'd-stroke vs Ctrl+D duplicate'],
    ['KeyZ', 'ż', 'Polish z-dot vs Ctrl+Z undo'],
    ['KeyY', '>', 'AltGr+Y vs Ctrl+Y redo'],
    ['KeyQ', '@', 'de at sign'],
  ])('AltGr+%s ("%s", %s) resolves to nothing', (code, char) => {
    expect(resolveBoqShortcut(altGr(code, char), idle)).toBeNull();
    expect(resolveBoqShortcut(altGr(code, char), editing)).toBeNull();
  });

  it('AltGr reported only through getModifierState still counts as AltGr', () => {
    const e: BoqShortcutKey = {
      key: '€', code: 'KeyE', ctrlKey: true, altKey: false,
      getModifierState: (k: string) => k === 'AltGraph',
    };
    expect(isAltOrAltGraph(e)).toBe(true);
    expect(isCommandChord(e)).toBe(false);
    expect(resolveBoqShortcut(e, idle)).toBeNull();
  });

  it('reads a real KeyboardEvent the same way', () => {
    const e = new KeyboardEvent('keydown', { key: '€', code: 'KeyE', ctrlKey: true, altKey: true });
    expect(resolveBoqShortcut(e, idle)).toBeNull();
    const plain = new KeyboardEvent('keydown', { key: 'e', code: 'KeyE', ctrlKey: true });
    expect(resolveBoqShortcut(plain, idle)).toBe('export_excel');
  });
});

describe('Ctrl+E / Ctrl+I / Ctrl+L wait for the cell editor to close', () => {
  it('Ctrl+E outside an editor still exports', () => {
    expect(resolveBoqShortcut(ctrl('e'), idle)).toBe('export_excel');
  });

  it('Ctrl+E inside an editor does nothing', () => {
    expect(resolveBoqShortcut(ctrl('e'), editing)).toBeNull();
  });

  it('Cmd+E on macOS behaves like Ctrl+E', () => {
    expect(resolveBoqShortcut(ctrl('e', { ctrlKey: false, metaKey: true }), idle)).toBe('export_excel');
  });

  it('matches the physical key on layouts that move the letter', () => {
    // A layout whose KeyE key types something other than "e".
    expect(resolveBoqShortcut(ctrl('e', { key: 'é' }), idle)).toBe('export_excel');
  });

  it('Ctrl+I imports and Ctrl+L toggles the lock, only when not editing', () => {
    expect(resolveBoqShortcut(ctrl('i'), idle)).toBe('import');
    expect(resolveBoqShortcut(ctrl('l'), idle)).toBe('toggle_lock');
    expect(resolveBoqShortcut(ctrl('i'), editing)).toBeNull();
    expect(resolveBoqShortcut(ctrl('l'), editing)).toBeNull();
  });

  it('Ctrl+D duplicates only outside an editor', () => {
    expect(resolveBoqShortcut(ctrl('d'), idle)).toBe('duplicate');
    expect(resolveBoqShortcut(ctrl('d'), editing)).toBeNull();
  });

  it('Ctrl+Shift+E is not the export', () => {
    expect(resolveBoqShortcut(ctrl('E', { shiftKey: true }), idle)).toBeNull();
  });
});

describe('shortcuts that keep working while typing', () => {
  it('Ctrl+Z undoes and Ctrl+Y / Ctrl+Shift+Z redo, editing or not', () => {
    for (const state of [idle, editing]) {
      expect(resolveBoqShortcut(ctrl('z'), state)).toBe('undo');
      expect(resolveBoqShortcut(ctrl('y'), state)).toBe('redo');
      expect(resolveBoqShortcut(ctrl('Z', { shiftKey: true }), state)).toBe('redo');
    }
  });

  it('Ctrl+Shift+V opens paste-from-Excel and Ctrl+Enter adds a position', () => {
    expect(resolveBoqShortcut(ctrl('V', { shiftKey: true }), editing)).toBe('paste_from_excel');
    expect(resolveBoqShortcut(ctrl('Enter', { code: 'Enter' }), editing)).toBe('add_position');
  });

  it('F1 and Ctrl+Shift+? open the shortcut overlay', () => {
    expect(resolveBoqShortcut({ key: 'F1', code: 'F1' }, editing)).toBe('toggle_shortcuts');
    expect(resolveBoqShortcut(ctrl('?', { shiftKey: true, code: 'Slash' }), idle)).toBe('toggle_shortcuts');
  });

  it('Ctrl+/ toggles the AI chat', () => {
    expect(resolveBoqShortcut(ctrl('/', { code: 'Slash' }), editing)).toBe('toggle_ai_chat');
  });

  it('plain typing is never a shortcut', () => {
    expect(resolveBoqShortcut({ key: 'e', code: 'KeyE' }, editing)).toBeNull();
    expect(resolveBoqShortcut({ key: ',', code: 'Comma' }, editing)).toBeNull();
    expect(resolveBoqShortcut({ key: '5', code: 'Digit5' }, idle)).toBeNull();
  });

  it('survives events with no key or code (IME / synthetic)', () => {
    expect(resolveBoqShortcut({ ctrlKey: true }, idle)).toBeNull();
  });
});

describe('the rest of the editor keys', () => {
  it('Alt+I toggles the copilot, AltGr+I and Ctrl+Alt+I do not', () => {
    expect(resolveBoqShortcut({ key: 'i', code: 'KeyI', altKey: true }, idle)).toBe('toggle_ai_copilot');
    expect(resolveBoqShortcut(altGr('KeyI', 'í'), idle)).toBeNull();
    expect(resolveBoqShortcut({ key: 'i', code: 'KeyI', altKey: true }, editing)).toBeNull();
  });

  it('Delete removes the selection only when rows are ticked and nothing is being edited', () => {
    expect(resolveBoqShortcut({ key: 'Delete' }, { isEditing: false, hasSelection: true })).toBe('delete_selected');
    expect(resolveBoqShortcut({ key: 'Backspace' }, { isEditing: false, hasSelection: true })).toBe('delete_selected');
    expect(resolveBoqShortcut({ key: 'Delete' }, { isEditing: false, hasSelection: false })).toBeNull();
    expect(resolveBoqShortcut({ key: 'Backspace' }, { isEditing: true, hasSelection: true })).toBeNull();
  });

  it('Delete does nothing for a user without the delete permission', () => {
    // A viewer could tick rows and press Delete: the rows vanished, the undo
    // toast ran and only the server's 403 five seconds later said otherwise.
    const noDelete = { isEditing: false, hasSelection: true, canDelete: false };
    expect(resolveBoqShortcut({ key: 'Delete' }, noDelete)).toBeNull();
    expect(resolveBoqShortcut({ key: 'Backspace' }, noDelete)).toBeNull();
    expect(resolveBoqShortcut({ key: 'Delete' }, { ...noDelete, canDelete: true })).toBe('delete_selected');
  });
});

describe('isTextEntryElement', () => {
  it('recognises form fields and contenteditable', () => {
    for (const tag of ['input', 'textarea', 'select']) {
      const el = document.createElement(tag);
      document.body.appendChild(el);
      expect(isTextEntryElement(el), tag).toBe(true);
    }
    const editable = document.createElement('div');
    editable.contentEditable = 'true';
    document.body.appendChild(editable);
    // jsdom does not compute isContentEditable; emulate what a browser reports.
    Object.defineProperty(editable, 'isContentEditable', { value: true });
    expect(isTextEntryElement(editable)).toBe(true);
  });

  it('recognises anything inside an open AG Grid cell editor', () => {
    document.body.innerHTML =
      '<div class="ag-cell ag-cell-inline-editing"><div><span id="inner">x</span></div></div>' +
      '<div class="ag-popup-editor"><button id="popup-btn">ok</button></div>';
    expect(isTextEntryElement(document.getElementById('inner'))).toBe(true);
    expect(isTextEntryElement(document.getElementById('popup-btn'))).toBe(true);
  });

  it('does not treat a focused, non-editing grid cell or the page body as typing', () => {
    document.body.innerHTML = '<div class="ag-cell ag-cell-focus" tabindex="0" id="cell">12,50</div>';
    expect(isTextEntryElement(document.getElementById('cell'))).toBe(false);
    expect(isTextEntryElement(document.body)).toBe(false);
    expect(isTextEntryElement(null)).toBe(false);
    expect(isTextEntryElement(window)).toBe(false);
  });
});
