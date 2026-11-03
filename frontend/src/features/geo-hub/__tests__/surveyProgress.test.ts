import { describe, expect, it } from 'vitest';

import {
  compareOpacities,
  formatGsd,
  formatSize,
  formatVariance,
  parseObservedPct,
  sortSurveys,
  statusFor,
  todayIso,
  validateUploadForm,
  varianceBadge,
} from '../surveyProgress';

describe('statusFor', () => {
  it('treats a missing variance as unobserved', () => {
    expect(statusFor(null)).toBe('unobserved');
    expect(statusFor(undefined)).toBe('unobserved');
    expect(statusFor(Number.NaN)).toBe('unobserved');
  });

  it('is on track within 5 points either way, inclusive', () => {
    expect(statusFor(0)).toBe('on_track');
    expect(statusFor(5)).toBe('on_track');
    expect(statusFor(-5)).toBe('on_track');
  });

  it('is ahead above and behind below the tolerance', () => {
    expect(statusFor(5.01)).toBe('ahead');
    expect(statusFor(-5.01)).toBe('behind');
    expect(statusFor(40)).toBe('ahead');
  });

  it('honours a custom tolerance', () => {
    expect(statusFor(8, 10)).toBe('on_track');
    expect(statusFor(-8, 2)).toBe('behind');
  });
});

describe('varianceBadge', () => {
  it('colours ahead, on track and behind differently', () => {
    expect(varianceBadge('ahead').variant).toBe('blue');
    expect(varianceBadge('on_track').variant).toBe('success');
    expect(varianceBadge('behind').variant).toBe('error');
    expect(varianceBadge('unobserved').variant).toBe('neutral');
  });

  it('points every status at a geo_hub.surveys.status key', () => {
    for (const s of ['ahead', 'on_track', 'behind', 'unobserved'] as const) {
      expect(varianceBadge(s).labelKey).toBe(`geo_hub.surveys.status.${s}`);
    }
  });
});

describe('formatVariance', () => {
  it('signs positive values and shows a dash when empty', () => {
    expect(formatVariance(20)).toBe('+20.0');
    expect(formatVariance(-5.5)).toBe('-5.5');
    expect(formatVariance(0)).toBe('0.0');
    expect(formatVariance(null)).toBe('—');
  });
});

describe('parseObservedPct', () => {
  it('accepts plain, decimal, comma and percent input', () => {
    expect(parseObservedPct('65')).toEqual({ ok: true, value: 65 });
    expect(parseObservedPct(' 65.5 ')).toEqual({ ok: true, value: 65.5 });
    expect(parseObservedPct('65,5%')).toEqual({ ok: true, value: 65.5 });
    expect(parseObservedPct('0')).toEqual({ ok: true, value: 0 });
    expect(parseObservedPct('100')).toEqual({ ok: true, value: 100 });
  });

  it('rejects empty, out of range and non numeric input', () => {
    for (const raw of ['', ' ', '101', '100.01', '-1', 'abc', '1e2', '5.123']) {
      expect(parseObservedPct(raw)).toEqual({ ok: false });
    }
  });
});

describe('validateUploadForm', () => {
  const today = '2026-06-15';

  it('passes with a tif file and a past date', () => {
    expect(validateUploadForm({ file: { name: 'Site.TIF' }, scanId: null, capturedOn: '2026-06-01' }, today)).toEqual([]);
    expect(validateUploadForm({ file: { name: 'a.tiff' }, scanId: null, capturedOn: today }, today)).toEqual([]);
  });

  it('passes with a scan instead of a file', () => {
    expect(validateUploadForm({ file: null, scanId: 'scan-1', capturedOn: '2026-06-01' }, today)).toEqual([]);
  });

  it('asks for a source', () => {
    expect(validateUploadForm({ file: null, scanId: null, capturedOn: '2026-06-01' }, today)).toEqual(['source_required']);
  });

  it('refuses anything but tif and tiff', () => {
    expect(validateUploadForm({ file: { name: 'a.png' }, scanId: null, capturedOn: '2026-06-01' }, today)).toEqual(['file_type']);
  });

  it('needs a real date that is not in the future', () => {
    expect(validateUploadForm({ file: null, scanId: 's', capturedOn: '' }, today)).toEqual(['date_required']);
    expect(validateUploadForm({ file: null, scanId: 's', capturedOn: '2026-06-16' }, today)).toEqual(['date_future']);
  });

  it('reports several problems at once', () => {
    expect(validateUploadForm({ file: { name: 'x.jpg' }, scanId: null, capturedOn: '' }, today)).toEqual([
      'file_type',
      'date_required',
    ]);
  });
});

describe('todayIso', () => {
  it('formats the local day with zero padding', () => {
    expect(todayIso(new Date(2026, 0, 5, 23, 59))).toBe('2026-01-05');
  });
});

describe('sortSurveys', () => {
  it('puts the newest capture first and does not mutate the input', () => {
    const list = [
      { captured_on: '2026-03-01', created_at: '2026-03-02T00:00:00Z' },
      { captured_on: '2026-05-01', created_at: '2026-05-02T00:00:00Z' },
      { captured_on: '2026-05-01', created_at: '2026-05-03T00:00:00Z' },
    ];
    const sorted = sortSurveys(list);
    expect(sorted.map((s) => s.created_at)).toEqual([
      '2026-05-03T00:00:00Z',
      '2026-05-02T00:00:00Z',
      '2026-03-02T00:00:00Z',
    ]);
    expect(list[0]?.captured_on).toBe('2026-03-01');
  });
});

describe('compareOpacities', () => {
  it('fades from the earlier to the later survey', () => {
    expect(compareOpacities(0)).toEqual({ earlier: 1, later: 0 });
    expect(compareOpacities(0.5)).toEqual({ earlier: 0.5, later: 0.5 });
    expect(compareOpacities(1)).toEqual({ earlier: 0, later: 1 });
  });

  it('clamps out of range and non finite input', () => {
    expect(compareOpacities(2)).toEqual({ earlier: 0, later: 1 });
    expect(compareOpacities(-1)).toEqual({ earlier: 1, later: 0 });
    expect(compareOpacities(Number.NaN)).toEqual({ earlier: 1, later: 0 });
  });
});

describe('result chips', () => {
  it('formats GSD in centimetres or metres', () => {
    expect(formatGsd('3.20')).toBe('3.2 cm/px');
    expect(formatGsd(677.38)).toBe('6.77 m/px');
    expect(formatGsd(null)).toBeNull();
    expect(formatGsd('')).toBeNull();
  });

  it('formats the pixel size only when both sides are known', () => {
    expect(formatSize(4000, 3000)).toBe('4000 × 3000 px');
    expect(formatSize(4000, null)).toBeNull();
  });
});
