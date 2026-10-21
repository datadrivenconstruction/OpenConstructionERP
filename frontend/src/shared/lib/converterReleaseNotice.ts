// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The "new converters, tell us if something looks wrong" notice.
 *
 * To extend the notice, change the date below; nothing else needs touching.
 */

/** Last moment the notice is shown, in local time (31 Oct 2026, 23:59:59). */
export const CONVERTER_NOTICE_UNTIL = new Date(2026, 9, 31, 23, 59, 59);

export const CONVERTER_ISSUES_URL = 'https://github.com/datadrivenconstruction/OpenConstructionERP/issues/new';
export const CONVERTER_CONTACT_EMAIL = 'info@datadrivenconstruction.io';

export function isConverterNoticeActive(now: Date = new Date()): boolean {
  return now.getTime() <= CONVERTER_NOTICE_UNTIL.getTime();
}

function storageKey(userId: string | null | undefined): string {
  return `oe_converter_release_notice_dismissed:${userId || 'anon'}`;
}

export function isConverterNoticeDismissed(userId: string | null | undefined): boolean {
  try {
    return localStorage.getItem(storageKey(userId)) === '1';
  } catch {
    return false;
  }
}

export function dismissConverterNotice(userId: string | null | undefined): void {
  try {
    localStorage.setItem(storageKey(userId), '1');
  } catch {
    // storage blocked: the notice simply reappears next visit
  }
}

export interface ConverterReportInfo {
  /** Upper-case format, for example `RVT`. */
  format?: string;
  /** Installed converter version when known. */
  converterVersion?: string | null;
  appVersion: string;
}

function reportBody(info: ConverterReportInfo): string {
  return [
    `Format: ${info.format || 'unknown'}`,
    `Converter version: ${info.converterVersion || 'unknown'}`,
    `App version: ${info.appVersion}`,
    '',
    'What happened:',
    '',
  ].join('\n');
}

export function converterReportUrl(info: ConverterReportInfo): string {
  const q = new URLSearchParams({ title: 'Converter: ', body: reportBody(info) });
  return `${CONVERTER_ISSUES_URL}?${q.toString()}`;
}

export function converterMailtoUrl(info: ConverterReportInfo): string {
  const subject = encodeURIComponent('Converter: ');
  const body = encodeURIComponent(reportBody(info));
  return `mailto:${CONVERTER_CONTACT_EMAIL}?subject=${subject}&body=${body}`;
}
