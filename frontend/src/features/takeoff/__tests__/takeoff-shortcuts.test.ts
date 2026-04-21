import { describe, it, expect } from 'vitest';
import {
  TOOL_SHORTCUT_MAP,
  SHORTCUT_LETTER,
  shortcutToTool,
  labelWithShortcut,
  shouldHandleShortcut,
} from '../lib/takeoff-shortcuts';

describe('takeoff-shortcuts', () => {
  describe('shortcutToTool', () => {
    it('maps V → select', () => {
      expect(shortcutToTool('V')).toBe('select');
      expect(shortcutToTool('v')).toBe('select');
    });

    it('maps all Q1 UX tool letters', () => {
      expect(shortcutToTool('D')).toBe('distance');
      expect(shortcutToTool('P')).toBe('polyline');
      expect(shortcutToTool('A')).toBe('area');
      expect(shortcutToTool('O')).toBe('volume');
      expect(shortcutToTool('C')).toBe('count');
      expect(shortcutToTool('R')).toBe('rectangle');
      expect(shortcutToTool('T')).toBe('text');
      expect(shortcutToTool('H')).toBe('highlight');
      expect(shortcutToTool('W')).toBe('cloud');
      expect(shortcutToTool('X')).toBe('arrow');
    });

    it('returns null for unmapped keys', () => {
      expect(shortcutToTool('Z')).toBeNull();
      expect(shortcutToTool('1')).toBeNull();
      expect(shortcutToTool('Escape')).toBeNull();
      expect(shortcutToTool('')).toBeNull();
    });

    it('is case-insensitive', () => {
      expect(shortcutToTool('d')).toBe(shortcutToTool('D'));
      expect(shortcutToTool('c')).toBe(shortcutToTool('C'));
    });
  });

  describe('SHORTCUT_LETTER', () => {
    it('has a letter for every tool in TOOL_SHORTCUT_MAP', () => {
      const tools = new Set(Object.values(TOOL_SHORTCUT_MAP));
      for (const tool of tools) {
        expect(SHORTCUT_LETTER[tool]).toBeDefined();
      }
    });

    it('uses uppercase letters', () => {
      for (const letter of Object.values(SHORTCUT_LETTER)) {
        expect(letter).toBe(letter.toUpperCase());
        expect(letter).toHaveLength(1);
      }
    });
  });

  describe('labelWithShortcut', () => {
    it('appends the letter in parens', () => {
      expect(labelWithShortcut('Distance', 'distance')).toBe('Distance (D)');
      expect(labelWithShortcut('Select', 'select')).toBe('Select (V)');
    });
  });

  describe('shouldHandleShortcut', () => {
    it('returns true for null target', () => {
      expect(shouldHandleShortcut(null)).toBe(true);
    });

    it('returns false for input elements', () => {
      const input = document.createElement('input');
      expect(shouldHandleShortcut(input)).toBe(false);
    });

    it('returns false for textareas', () => {
      const textarea = document.createElement('textarea');
      expect(shouldHandleShortcut(textarea)).toBe(false);
    });

    it('returns false for selects', () => {
      const select = document.createElement('select');
      expect(shouldHandleShortcut(select)).toBe(false);
    });

    it('returns true for non-input elements', () => {
      const div = document.createElement('div');
      expect(shouldHandleShortcut(div)).toBe(true);
    });

    it('returns false for contenteditable', () => {
      const div = document.createElement('div');
      div.setAttribute('contenteditable', 'true');
      // jsdom exposes `isContentEditable` as a getter tied to the attribute.
      Object.defineProperty(div, 'isContentEditable', { value: true });
      expect(shouldHandleShortcut(div)).toBe(false);
    });
  });
});
