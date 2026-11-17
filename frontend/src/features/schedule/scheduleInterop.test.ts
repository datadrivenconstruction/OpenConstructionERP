// @vitest-environment node
import { describe, it, expect } from 'vitest';
import {
  canImportChecked,
  deltaTone,
  fileKey,
  isMspXmlFile,
  signedDays,
  splitIssues,
} from './scheduleInterop';

const issue = (severity: string, code: string) =>
  ({ rule_id: 'r', code, severity, ref: '1', message: code }) as never;

const preview = (can_apply: boolean) => ({ can_apply }) as never;

describe('schedule interop helpers', () => {
  it('routes only .xml files through the check step', () => {
    expect(isMspXmlFile('Plan.XML')).toBe(true);
    expect(isMspXmlFile('plan.xer')).toBe(false);
    expect(isMspXmlFile(null)).toBe(false);
  });

  it('puts errors before warnings', () => {
    const { errors, warnings } = splitIssues([
      issue('warning', 'dangling_link'),
      issue('error', 'missing_dates'),
    ]);
    expect(errors.map((i) => i.code)).toEqual(['missing_dates']);
    expect(warnings.map((i) => i.code)).toEqual(['dangling_link']);
  });

  it('allows import only for the checked file without errors', () => {
    const file = { name: 'a.xml', size: 10, lastModified: 5 };
    const other = { name: 'b.xml', size: 10, lastModified: 5 };
    const key = fileKey(file);
    expect(canImportChecked(preview(true), file, key)).toBe(true);
    expect(canImportChecked(preview(false), file, key)).toBe(false);
    expect(canImportChecked(preview(true), other, key)).toBe(false);
    expect(canImportChecked(null, file, key)).toBe(false);
  });

  it('signs day deltas and colours money deltas', () => {
    expect(signedDays(5)).toBe('+5');
    expect(signedDays(-2)).toBe('-2');
    expect(signedDays(0)).toBe('0');
    expect(signedDays(null)).toBe('');
    expect(deltaTone('6000')).toBe('up');
    expect(deltaTone('-1000.50')).toBe('down');
    expect(deltaTone('0')).toBe('flat');
    expect(deltaTone(null)).toBe('none');
  });
});
