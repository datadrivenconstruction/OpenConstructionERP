// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A failed DWG conversion showed the converter's JSON report with the server
 * path of the upload, in English whatever the UI language. The page now
 * translates the stable ``metadata.error_code`` and never shows a dump.
 */

import { describe, it, expect } from 'vitest';
import { conversionErrorText } from '../conversion-error';

const t = (key: string, opts: { defaultValue: string }) => `[${key}] ${opts.defaultValue}`;

describe('conversionErrorText', () => {
  it('translates a known code and ignores the English message', () => {
    const text = conversionErrorText('convert_failed', 'English text with C:\\data\\dwg_uploads\\x.dwg', t);
    expect(text).toContain('[dwg_takeoff.conv_err_convert_failed]');
    expect(text).toContain('DXF');
    expect(text).not.toContain('dwg_uploads');
  });

  it.each(['parse_failed', 'not_dwg', 'dwg_too_old', 'convert_timeout'])('has a key for %s', (code) => {
    expect(conversionErrorText(code, null, t)).toContain(`[dwg_takeoff.conv_err_${code}]`);
  });

  it('strips the converter dump from a legacy message without a code', () => {
    const legacy =
      'The DWG converter could not process this file (exit 3, FAILED). Try exporting the drawing as DXF. ' +
      'Details: {"input": "C:\\\\Users\\\\me\\\\dwg_uploads\\\\a.dwg", "status": "FAILED"}';
    const text = conversionErrorText(null, legacy, t);
    expect(text).not.toContain('Details');
    expect(text).not.toContain('dwg_uploads');
    expect(text).toContain('Try exporting the drawing as DXF.');
  });

  it('returns null when there is nothing to say', () => {
    expect(conversionErrorText(undefined, null, t)).toBeNull();
  });
});
