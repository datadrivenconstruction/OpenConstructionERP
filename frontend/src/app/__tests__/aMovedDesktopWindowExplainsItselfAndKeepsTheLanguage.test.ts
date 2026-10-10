import { describe, expect, it } from 'vitest';

import { accountLanguageToApply } from '../accountLanguage';
import { movedDesktopPort } from '@/shared/ui/DesktopPortBanner';

/**
 * The desktop window is served from 127.0.0.1 and a port, and the browser
 * keeps sign-in and language per port. When another program holds 8732 the
 * window opens on a fallback port with empty storage. These pin the two
 * answers to that: the window says why once, and the account's language comes
 * back after sign-in instead of the browser's.
 */
describe('a desktop window on another port says so', () => {
  it('names the port only for the desktop window on this computer, off the default', () => {
    expect(movedDesktopPort(true, { hostname: '127.0.0.1', port: '8733' })).toBe('8733');
    expect(movedDesktopPort(true, { hostname: 'localhost', port: '8740' })).toBe('8740');
    expect(movedDesktopPort(true, { hostname: '127.0.0.1', port: '8732' })).toBeNull();
    expect(movedDesktopPort(false, { hostname: '127.0.0.1', port: '8733' })).toBeNull();
    // A desktop app pointed at a server elsewhere: its port is that server's.
    expect(movedDesktopPort(true, { hostname: 'erp.example.com', port: '8443' })).toBeNull();
    expect(movedDesktopPort(true, { hostname: '127.0.0.1', port: '' })).toBeNull();
  });
});

describe('the account language comes back on a fresh origin', () => {
  const supported = ['en', 'de', 'it', 'ru'];

  it('restores the account language when this origin held no choice', () => {
    expect(accountLanguageToApply('it', 'en', false, supported)).toBe('it');
  });

  it('never overrides a language chosen in this browser', () => {
    expect(accountLanguageToApply('it', 'de', true, supported)).toBeNull();
  });

  it('does not treat the column default en as a choice', () => {
    expect(accountLanguageToApply('en', 'de', false, supported)).toBeNull();
  });

  it('ignores an empty, unknown or already active language', () => {
    expect(accountLanguageToApply(null, 'en', false, supported)).toBeNull();
    expect(accountLanguageToApply('', 'en', false, supported)).toBeNull();
    expect(accountLanguageToApply('xx', 'en', false, supported)).toBeNull();
    expect(accountLanguageToApply('de', 'de', false, supported)).toBeNull();
  });
});
