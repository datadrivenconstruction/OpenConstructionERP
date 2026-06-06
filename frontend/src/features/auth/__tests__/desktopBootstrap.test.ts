import { describe, expect, it } from 'vitest';

import {
  shouldAttemptDesktopBootstrap,
  shouldQueryFirstRun,
  type FirstRunStatus,
} from '../desktopBootstrap';

/** Convenience builder so each case spells out only what it changes. */
function status(overrides: Partial<FirstRunStatus> = {}): FirstRunStatus {
  return {
    desktop_mode: true,
    fresh_install: true,
    has_local_account: false,
    onboarding_completed: null,
    ...overrides,
  };
}

describe('shouldQueryFirstRun', () => {
  it('queries in Tauri with no token and no manual flag', () => {
    expect(shouldQueryFirstRun(true, false, null)).toBe(true);
  });

  it('does not query outside Tauri', () => {
    expect(shouldQueryFirstRun(false, false, null)).toBe(false);
  });

  it('does not query when a token is already stored', () => {
    expect(shouldQueryFirstRun(true, true, null)).toBe(false);
  });

  it('does not query after a deliberate manual logout', () => {
    expect(shouldQueryFirstRun(true, false, '1')).toBe(false);
  });

  it('ignores stale / non-"1" manual flag values', () => {
    expect(shouldQueryFirstRun(true, false, '0')).toBe(true);
    expect(shouldQueryFirstRun(true, false, '')).toBe(true);
  });
});

describe('shouldAttemptDesktopBootstrap', () => {
  it('bootstraps a fresh desktop install', () => {
    expect(shouldAttemptDesktopBootstrap(status(), false, null)).toBe(true);
  });

  it('bootstraps when a local account already exists', () => {
    expect(
      shouldAttemptDesktopBootstrap(
        status({ fresh_install: false, has_local_account: true }),
        false,
        null,
      ),
    ).toBe(true);
  });

  it('does not bootstrap when status is null (fetch failed)', () => {
    expect(shouldAttemptDesktopBootstrap(null, false, null)).toBe(false);
  });

  it('does not bootstrap when not in desktop mode', () => {
    expect(
      shouldAttemptDesktopBootstrap(status({ desktop_mode: false }), false, null),
    ).toBe(false);
  });

  it('does not bootstrap into a workspace with real users but no local owner', () => {
    expect(
      shouldAttemptDesktopBootstrap(
        status({ fresh_install: false, has_local_account: false }),
        false,
        null,
      ),
    ).toBe(false);
  });

  it('does not bootstrap when a token is already stored', () => {
    expect(shouldAttemptDesktopBootstrap(status(), true, null)).toBe(false);
  });

  it('does not bootstrap after a deliberate manual logout', () => {
    expect(shouldAttemptDesktopBootstrap(status(), false, '1')).toBe(false);
  });
});
