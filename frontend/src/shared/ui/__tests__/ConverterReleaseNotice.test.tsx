// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The release notice stops on its cutoff date and stays dismissed per user.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ConverterReleaseNotice } from '../ConverterReleaseNotice';
import {
  CONVERTER_NOTICE_UNTIL,
  converterMailtoUrl,
  converterReportUrl,
  isConverterNoticeActive,
} from '@/shared/lib/converterReleaseNotice';

beforeEach(() => localStorage.clear());
afterEach(() => vi.useRealTimers());

describe('converter release notice', () => {
  it('is active through 31 Oct 2026 23:59 local time and off after', () => {
    expect(isConverterNoticeActive(new Date(2026, 9, 31, 23, 58))).toBe(true);
    expect(isConverterNoticeActive(new Date(2026, 10, 1, 0, 0))).toBe(false);
    expect(CONVERTER_NOTICE_UNTIL.getMonth()).toBe(9);
  });

  it('renders before the cutoff and hides itself after dismiss, remembered across mounts', () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date(2026, 9, 21, 12, 0));
    const first = render(<ConverterReleaseNotice format="RVT" />);
    expect(screen.getByTestId('converter-release-notice')).toBeTruthy();
    fireEvent.click(screen.getByTestId('converter-notice-dismiss'));
    expect(screen.queryByTestId('converter-release-notice')).toBeNull();
    first.unmount();
    render(<ConverterReleaseNotice format="RVT" />);
    expect(screen.queryByTestId('converter-release-notice')).toBeNull();
  });

  it('renders nothing after the cutoff', () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date(2026, 10, 2, 9, 0));
    render(<ConverterReleaseNotice />);
    expect(screen.queryByTestId('converter-release-notice')).toBeNull();
  });

  it('prefills the report with format and versions only', () => {
    const info = { format: 'IFC', converterVersion: '18.0.0.0', appVersion: '18.8.0' };
    const url = decodeURIComponent(converterReportUrl(info).replace(/\+/g, ' '));
    expect(url).toContain('issues/new?title=Converter: ');
    expect(url).toContain('Format: IFC');
    expect(url).toContain('Converter version: 18.0.0.0');
    expect(converterMailtoUrl(info)).toMatch(/^mailto:info@datadrivenconstruction\.io\?/);
  });
});
