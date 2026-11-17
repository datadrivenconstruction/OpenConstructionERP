// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { captureSourceOf, isCapturable, uploadBatch } from '../invoiceCaptureIntake';

const f = (name: string, type: string) => ({ name, type }) as File;

describe('isCapturable', () => {
  it('accepts pdf, images and e-invoice xml', () => {
    expect(isCapturable(f('a.pdf', 'application/pdf'))).toBe(true);
    expect(isCapturable(f('IMG_1.jpg', 'image/jpeg'))).toBe(true);
    expect(isCapturable(f('scan.HEIC', ''))).toBe(true);
    expect(isCapturable(f('inv.xml', 'text/xml'))).toBe(true);
  });
  it('rejects other files', () => {
    expect(isCapturable(f('tool.exe', 'application/octet-stream'))).toBe(false);
    expect(isCapturable(f('notes.docx', ''))).toBe(false);
  });
});

describe('captureSourceOf', () => {
  it('keeps known sources and falls back to upload', () => {
    expect(captureSourceOf('email')).toBe('email');
    expect(captureSourceOf('camera')).toBe('camera');
    expect(captureSourceOf(undefined)).toBe('upload');
    expect(captureSourceOf('fax')).toBe('upload');
  });
});

describe('uploadBatch', () => {
  it('uploads in order, reports skipped and failed files, and keeps going', async () => {
    const seen: string[] = [];
    const out = await uploadBatch(
      [f('a.pdf', 'application/pdf'), f('x.exe', ''), f('bad.png', 'image/png'), f('c.pdf', 'application/pdf')],
      async (file) => {
        seen.push(file.name);
        if (file.name === 'bad.png') throw new Error('too large');
        return file.name;
      },
    );
    expect(seen).toEqual(['a.pdf', 'bad.png', 'c.pdf']);
    expect(out.captured).toEqual(['a.pdf', 'c.pdf']);
    expect(out.skipped).toEqual(['x.exe']);
    expect(out.failed).toEqual([{ name: 'bad.png', message: 'too large' }]);
  });
});
