// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { afterEach, describe, expect, it } from 'vitest';

import {
  TRAINER_DOCK_ATTR,
  TRAINER_DOCK_OFFSET_VAR,
  TRAINER_RAIL_WIDTH,
  TRAINER_SHEET_PEEK_VAR,
  applyTrainerDockLayout,
  clearTrainerDockLayout,
  readInlinePx,
  resolveTrainerDockMode,
  trainerDockFits,
  trainerDockMaxWidth,
  trainerDockOffset,
  trainerDockWidth,
  trainerWidthFromDrag,
  trainerWidthFromKey,
} from './dockGeometry';
import { DOCK_WIDTH_DEFAULT, DOCK_WIDTH_MAX, DOCK_WIDTH_MIN } from './useTrainerUiStore';

const desk = { viewportWidth: 1440, sidebarWidth: 248, aiOffset: 0 };

afterEach(() => clearTrainerDockLayout(document.documentElement));

describe('which presentation the dock takes', () => {
  it('is a bottom sheet below 640px, whatever the open flag says', () => {
    expect(resolveTrainerDockMode({ viewportWidth: 639, sidebarWidth: 0, aiOffset: 0, open: true })).toBe('sheet');
    expect(resolveTrainerDockMode({ viewportWidth: 375, sidebarWidth: 0, aiOffset: 0, open: false })).toBe('sheet');
  });

  it('pushes when open and folds to the rail when collapsed', () => {
    expect(resolveTrainerDockMode({ ...desk, open: true })).toBe('push');
    expect(resolveTrainerDockMode({ ...desk, open: false })).toBe('rail');
    expect(resolveTrainerDockMode({ viewportWidth: 640, sidebarWidth: 0, aiOffset: 0, open: false })).toBe('rail');
  });

  it('fits only from the lg breakpoint, with 560px of page left beside the narrowest panel', () => {
    expect(trainerDockFits(desk)).toBe(true);
    expect(trainerDockFits({ viewportWidth: 1023, sidebarWidth: 0, aiOffset: 0 })).toBe(false);
    // 1024 - 248 - 320 = 456 < 560
    expect(trainerDockFits({ viewportWidth: 1024, sidebarWidth: 248, aiOffset: 0 })).toBe(false);
    // exactly 560 left fits
    expect(trainerDockFits({ viewportWidth: 248 + DOCK_WIDTH_MIN + 560, sidebarWidth: 248, aiOffset: 0 })).toBe(true);
  });

  it('stops fitting when the AI dock opens beside it', () => {
    // 1440 - 248 - 440 - 320 = 432 < 560
    expect(trainerDockFits({ ...desk, aiOffset: 440 })).toBe(false);
    expect(trainerDockFits({ viewportWidth: 1920, sidebarWidth: 248, aiOffset: 440 })).toBe(true);
  });
});

describe('how wide the panel is', () => {
  it('caps the preference by the room the page leaves, never below the minimum', () => {
    expect(trainerDockMaxWidth(desk)).toBe(DOCK_WIDTH_MAX);
    expect(trainerDockMaxWidth({ viewportWidth: 1200, sidebarWidth: 248, aiOffset: 0 })).toBe(1200 - 248 - 560);
    expect(trainerDockMaxWidth({ viewportWidth: 800, sidebarWidth: 0, aiOffset: 0 })).toBe(DOCK_WIDTH_MIN);
    expect(trainerDockWidth(DOCK_WIDTH_DEFAULT, 1000)).toBe(DOCK_WIDTH_DEFAULT);
    expect(trainerDockWidth(900, 400)).toBe(400);
    expect(trainerDockWidth(100, 400)).toBe(DOCK_WIDTH_MIN);
    expect(trainerDockWidth(Number.NaN, 400)).toBe(DOCK_WIDTH_DEFAULT);
  });

  it('pads the page by the panel, the rail or nothing', () => {
    expect(trainerDockOffset('push', 401.6)).toBe(402);
    expect(trainerDockOffset('rail', 500)).toBe(TRAINER_RAIL_WIDTH);
    expect(trainerDockOffset('sheet', 500)).toBe(0);
  });
});

describe('resizing', () => {
  it('widens when the handle moves away from the panel, mirrored in RTL', () => {
    expect(trainerWidthFromDrag({ startWidth: 380, startX: 1000, currentX: 950, rtl: false, maxWidth: 560 })).toBe(430);
    expect(trainerWidthFromDrag({ startWidth: 380, startX: 400, currentX: 450, rtl: true, maxWidth: 560 })).toBe(430);
    expect(trainerWidthFromDrag({ startWidth: 380, startX: 1000, currentX: 500, rtl: false, maxWidth: 560 })).toBe(560);
  });

  it('steps 16px with the arrow towards the page, swapped in RTL; Home and End jump', () => {
    expect(trainerWidthFromKey('ArrowLeft', { width: 380, maxWidth: 560, rtl: false })).toBe(396);
    expect(trainerWidthFromKey('ArrowRight', { width: 380, maxWidth: 560, rtl: false })).toBe(364);
    expect(trainerWidthFromKey('ArrowRight', { width: 380, maxWidth: 560, rtl: true })).toBe(396);
    expect(trainerWidthFromKey('ArrowLeft', { width: 380, maxWidth: 560, rtl: true })).toBe(364);
    expect(trainerWidthFromKey('Home', { width: 380, maxWidth: 560, rtl: false })).toBe(DOCK_WIDTH_MIN);
    expect(trainerWidthFromKey('End', { width: 380, maxWidth: 500, rtl: false })).toBe(500);
    expect(trainerWidthFromKey('Enter', { width: 380, maxWidth: 560, rtl: false })).toBeNull();
  });
});

describe('the layout contract on <html>', () => {
  it('writes push for the panel and the rail, sheet for the phone, and clears all of it', () => {
    const root = document.documentElement;
    applyTrainerDockLayout(root, 'push', 380);
    expect(root.getAttribute(TRAINER_DOCK_ATTR)).toBe('push');
    expect(root.style.getPropertyValue(TRAINER_DOCK_OFFSET_VAR)).toBe('380px');
    expect(root.style.getPropertyValue(TRAINER_SHEET_PEEK_VAR)).toBe('');

    applyTrainerDockLayout(root, 'rail', 380);
    expect(root.getAttribute(TRAINER_DOCK_ATTR)).toBe('push');
    expect(root.style.getPropertyValue(TRAINER_DOCK_OFFSET_VAR)).toBe('56px');

    applyTrainerDockLayout(root, 'sheet', 380);
    expect(root.getAttribute(TRAINER_DOCK_ATTR)).toBe('sheet');
    expect(root.style.getPropertyValue(TRAINER_DOCK_OFFSET_VAR)).toBe('0px');
    expect(root.style.getPropertyValue(TRAINER_SHEET_PEEK_VAR)).toBe('64px');

    clearTrainerDockLayout(root);
    expect(root.hasAttribute(TRAINER_DOCK_ATTR)).toBe(false);
    expect(root.style.getPropertyValue(TRAINER_DOCK_OFFSET_VAR)).toBe('');
    expect(root.style.getPropertyValue(TRAINER_SHEET_PEEK_VAR)).toBe('');
  });

  it('reads an inline px variable, and 0 for anything else', () => {
    const root = document.documentElement;
    root.style.setProperty('--oe-test-px', '440px');
    expect(readInlinePx(root, '--oe-test-px')).toBe(440);
    root.style.setProperty('--oe-test-px', '2rem');
    expect(readInlinePx(root, '--oe-test-px')).toBe(0);
    root.style.removeProperty('--oe-test-px');
    expect(readInlinePx(root, '--oe-test-px')).toBe(0);
  });
});
