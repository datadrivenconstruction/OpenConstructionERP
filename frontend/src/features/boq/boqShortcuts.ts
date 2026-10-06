// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Keyboard shortcuts of the BOQ editor, as a pure decision.
 *
 * The editor listens for these on `document` in the capture phase, which means
 * it sees every keystroke typed into a grid cell before the cell editor does.
 * Two things follow from that, and both used to go wrong.
 *
 * AltGr. Windows reports AltGr as Ctrl+Alt, so a character typed with AltGr
 * arrives looking like a Ctrl chord. On Croatian, German, Czech and many other
 * layouts the euro sign is AltGr+E, the at sign is AltGr+V or AltGr+Q, and the
 * Polish layout types every accented letter with AltGr (AltGr+Z is z-dot). A
 * Croatian estimator typing "12,50 €" into a price cell started the Excel
 * export instead, and the euro sign never reached the cell. No shortcut here
 * wants Alt held together with Ctrl, so a chord with Alt or AltGraph is never
 * a Ctrl shortcut: it is text.
 *
 * Typing. The export, import and lock shortcuts used to fire while a cell was
 * being edited. Those three take over the screen (a download, a dialog, a
 * locked bill) in the middle of an entry, so they now wait until the editor is
 * closed. Undo, redo, paste-from-Excel, add-position and the AI chat toggle
 * keep firing while typing, as they always have.
 */

/** What a keystroke asks the BOQ editor to do. */
export type BoqShortcutAction =
  | 'toggle_shortcuts'
  | 'undo'
  | 'redo'
  | 'paste_from_excel'
  | 'add_position'
  | 'export_excel'
  | 'import'
  | 'toggle_lock'
  | 'toggle_ai_chat'
  | 'toggle_ai_copilot'
  | 'delete_selected'
  | 'duplicate';

/** The parts of a keyboard event the decision reads. */
export interface BoqShortcutKey {
  key?: string;
  code?: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
  getModifierState?: (keyArg: string) => boolean;
}

/** Editor state the decision depends on. */
export interface BoqShortcutState {
  /** Focus is in a cell editor or any other text entry. */
  isEditing: boolean;
  /** At least one position is ticked in the grid. */
  hasSelection: boolean;
  /** The user may delete positions (`boq.delete`). Only `false` disables
   *  the Delete key, so a caller that does not gate keeps working. */
  canDelete?: boolean;
}

/**
 * Alt or AltGr is held. On Windows AltGr sets both `ctrlKey` and `altKey`;
 * `getModifierState('AltGraph')` covers engines that report it separately.
 */
export function isAltOrAltGraph(e: BoqShortcutKey): boolean {
  if (e.altKey === true) return true;
  return typeof e.getModifierState === 'function' && e.getModifierState('AltGraph') === true;
}

/** A real Ctrl (or Cmd) chord: Ctrl/Cmd held, and neither Alt nor AltGr. */
export function isCommandChord(e: BoqShortcutKey): boolean {
  return (e.ctrlKey === true || e.metaKey === true) && !isAltOrAltGraph(e);
}

const TEXT_ENTRY_TAGS = new Set(['input', 'textarea', 'select']);

/**
 * True when `el` takes typed text: a form field, a contenteditable, or
 * anything inside an open AG Grid cell editor (inline or popup).
 */
export function isTextEntryElement(el: EventTarget | null | undefined): boolean {
  if (!el || typeof (el as Element).tagName !== 'string') return false;
  const element = el as HTMLElement;
  if (TEXT_ENTRY_TAGS.has(element.tagName.toLowerCase())) return true;
  if (element.isContentEditable === true) return true;
  return typeof element.closest === 'function'
    && element.closest('.ag-cell-inline-editing, .ag-popup-editor') !== null;
}

/**
 * Decide which shortcut, if any, a keystroke triggers. Returns null for
 * anything that is not a shortcut, which includes every AltGr character.
 */
export function resolveBoqShortcut(e: BoqShortcutKey, state: BoqShortcutState): BoqShortcutAction | null {
  const key = e.key ?? '';
  const k = key.toLowerCase();
  // #153 guard - e.key / e.code can be undefined for synthetic and IME events.
  const code = e.code ?? '';
  // Match the physical key as well so layouts that move the letter (AZERTY
  // and the like) still reach the shortcut printed on the key.
  const codeLetter = code.startsWith('Key') ? code.slice(3).toLowerCase() : '';
  const isCmd = isCommandChord(e);
  const shift = e.shiftKey === true;
  const isLetter = (letter: string) => k === letter || codeLetter === letter;

  // F1 and Ctrl+Shift+? open the shortcut overlay, even while typing.
  if (key === 'F1') return 'toggle_shortcuts';
  if (isCmd && shift && key === '?') return 'toggle_shortcuts';

  // Undo / redo / paste-from-Excel / add-position fire even while typing.
  if (isCmd && !shift && key === 'z') return 'undo';
  if ((isCmd && key === 'y') || (isCmd && shift && (key === 'z' || key === 'Z'))) return 'redo';
  if (isCmd && shift && (key === 'V' || key === 'v')) return 'paste_from_excel';
  if (isCmd && key === 'Enter') return 'add_position';

  // Ctrl+/ toggles the AI chat. e.code 'Slash' is the fallback for layouts
  // where '/' sits elsewhere.
  if (isCmd && (key === '/' || code === 'Slash')) return 'toggle_ai_chat';

  // Everything below waits until the cell editor (or any text field) is done.
  if (state.isEditing) return null;

  if (isCmd && !shift && isLetter('e')) return 'export_excel';
  if (isCmd && !shift && isLetter('i')) return 'import';
  if (isCmd && !shift && isLetter('l')) return 'toggle_lock';

  // Alt+I toggles the per-position AI copilot. Plain Alt only: Ctrl, Cmd
  // and AltGr+I (a letter on several layouts) are not it.
  const plainAlt = e.altKey === true && e.ctrlKey !== true && e.metaKey !== true
    && !(typeof e.getModifierState === 'function' && e.getModifierState('AltGraph') === true);
  if (plainAlt && !shift && isLetter('i')) return 'toggle_ai_copilot';

  if ((key === 'Delete' || key === 'Backspace') && state.hasSelection && state.canDelete !== false) {
    return 'delete_selected';
  }

  if (isCmd && !shift && isLetter('d')) return 'duplicate';

  return null;
}
