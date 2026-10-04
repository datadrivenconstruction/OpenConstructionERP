// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The public token routes (bidder link, buyer portal, share link, field login)
// carry their credential in the path. An error on those pages must not post
// the token to the server with the report.

import { afterEach, describe, expect, it } from 'vitest';

import { getErrorLog, logError, maskTokenPath } from './errorLogger';

const TOKEN = 'k3Y-secret_Token0123456789abcdefghijABCDEFGHIJ';

describe('error reports from a bidder link', () => {
  afterEach(() => {
    window.history.replaceState(null, '', '/');
  });

  it.each(['/tendering/bid/', '/buyer-portal/', '/share/', '/field/'])('masks the token of %s', (prefix) => {
    expect(maskTokenPath(`${prefix}${TOKEN}`)).toBe(`${prefix}:token`);
    expect(maskTokenPath(`${prefix}${TOKEN}/`)).toBe(`${prefix}:token/`);
  });

  it('leaves every other path as it is', () => {
    for (const path of [
      '/tendering',
      '/tendering/bid',
      '/tendering/bid/',
      '/field',
      '/field-reports',
      '/field-time/week',
      '/sharepoint/abc',
      '/projects/abc/boq',
    ]) {
      expect(maskTokenPath(path)).toBe(path);
    }
  });

  it('never records the token in a logged entry', () => {
    window.history.replaceState(null, '', `/tendering/bid/${TOKEN}`);
    logError('render failed on the price-entry page', 'js_error');
    const serialized = JSON.stringify(getErrorLog());
    expect(serialized).not.toContain(TOKEN);
    expect(serialized).toContain('/tendering/bid/:token');
  });
});
