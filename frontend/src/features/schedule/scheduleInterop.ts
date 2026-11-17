// Small pure helpers for the MS Project XML check-before-import flow and the
// revision-impact table. No React, so they test in a node environment.

import type { MspdiIssue, MspdiPreview } from './api';

/** True for a file the MS Project XML (MSPDI) path handles; XER goes straight to import. */
export function isMspXmlFile(name: string | null | undefined): boolean {
  return (name ?? '').toLowerCase().trim().endsWith('.xml');
}

/** Errors first (they block the import), then warnings. */
export function splitIssues(issues: MspdiIssue[]): { errors: MspdiIssue[]; warnings: MspdiIssue[] } {
  const errors = issues.filter((i) => i.severity === 'error');
  const warnings = issues.filter((i) => i.severity !== 'error');
  return { errors, warnings };
}

/** Import is allowed only for the file that was checked, and only when the check found no error. */
export function canImportChecked(
  preview: MspdiPreview | null,
  file: File | { name: string; size: number } | null,
  checkedKey: string | null,
): boolean {
  if (!preview || !file || !checkedKey) return false;
  return preview.can_apply && checkedKey === fileKey(file);
}

/** Identity of a chosen file, so a preview is never applied to a different file. */
export function fileKey(file: { name: string; size: number; lastModified?: number }): string {
  return `${file.name}:${file.size}:${file.lastModified ?? 0}`;
}

/** Signed whole days: "+5", "-2", "0"; empty when unknown. */
export function signedDays(days: number | null | undefined): string {
  if (days === null || days === undefined || Number.isNaN(days)) return '';
  if (days > 0) return `+${days}`;
  return String(days);
}

/** Direction of a decimal-string delta for colouring: later/costlier is "up". */
export function deltaTone(value: string | number | null | undefined): 'up' | 'down' | 'flat' | 'none' {
  if (value === null || value === undefined || value === '') return 'none';
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return 'none';
  if (n > 0) return 'up';
  if (n < 0) return 'down';
  return 'flat';
}
