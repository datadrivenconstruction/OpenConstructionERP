// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Small pieces every block of the payment certificate screen shares: what the
// blocks are told about the certificate, the anchors the attention strip
// jumps to, and how a server refusal is worded.

import type { ReactNode } from 'react';
import type { TFunction } from 'i18next';
import { AlertTriangle } from 'lucide-react';

import { normalizeRole, ROLE_RANK } from '@/shared/lib/roles';
import type { HakedisDocument, HakedisLocale, HakedisSource, HakedisSummaryLine } from './api';
import type { HakedisRefusal } from './hakedisQueries';

/** What every block of the screen is handed. */
export interface HakedisBlockProps {
  source: HakedisSource;
  doc: HakedisDocument;
  /** The language the certificate was read in; a write answers in the same one. */
  locale: HakedisLocale;
  /** The reader's number format, for figures printed inside sentences. */
  numberLocale: string;
  /** The reader may enter lines and choose taxes, and the document still takes it. */
  canEdit: boolean;
  /** Put a refreshed certificate, answered by a write, in place of the one shown. */
  onUpdated: (doc: HakedisDocument) => void;
}

/**
 * The reader's rank among the roles. An unknown role has no rank, so it is
 * offered nothing. The check only decides what to OFFER: the server decides
 * what is allowed.
 */
export function rankOf(role: string | null | undefined): number {
  const rank = (ROLE_RANK as Readonly<Record<string, number>>)[normalizeRole(role)];
  return rank ?? Number.NEGATIVE_INFINITY;
}

/** The id of one place on the screen, unique to the document shown. */
export function anchorId(source: HakedisSource, part: string): string {
  return `hakedis-${source.id}-${part}`;
}

export function lineAnchor(source: HakedisSource, lineKey: string): string {
  return anchorId(source, `line-${lineKey}`);
}

export function taxAnchor(source: HakedisSource, kind: string): string {
  return anchorId(source, `tax-${kind}`);
}

/** Bring one place of the screen into view and put the keyboard focus on it. */
export function jumpTo(id: string): void {
  const target = document.getElementById(id);
  if (!target) return;
  if (typeof target.scrollIntoView === 'function') target.scrollIntoView({ block: 'center' });
  target.focus({ preventScroll: true });
}

/** A summary line named the way the form names it: its letter, then its label. */
export function lineName(line: HakedisSummaryLine): string {
  const label = line.labels.join(' / ');
  return line.letter ? `${line.letter}) ${label}` : label;
}

/** Names a line by its key, for a reason that points at other lines. Unknown keys are passed through. */
export function lineNamer(doc: HakedisDocument): (key: string) => string {
  const byKey = new Map(doc.summary.map((line) => [line.key, line]));
  return (key) => {
    const line = byKey.get(key);
    return line ? lineName(line) : key;
  };
}

/**
 * A refusal in the reader's language.
 *
 * The certificate routes name a code (`hakedis.error.<code>`), the tax routes
 * send their own key. The server's sentence is the fallback for a code no
 * locale words yet, so a refusal is never shown as a bare code.
 */
export function refusalText(t: TFunction, refusal: HakedisRefusal): string {
  if (refusal.key) return t(refusal.key, { defaultValue: refusal.message });
  if (refusal.code) {
    return t(`hakedis.error.${refusal.code}`, { defaultValue: refusal.message, message: refusal.message });
  }
  return refusal.message;
}

/** The heading over one block. */
export function BlockTitle({ children, count }: { children: ReactNode; count?: number }) {
  return (
    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-secondary">
      {children}
      {count !== undefined && <span className="ml-2 normal-case text-content-tertiary">({count})</span>}
    </h3>
  );
}

/** A refusal shown where the person acted: the translated sentence, then the server's own words. */
export function RefusalNote({ t, refusal, testId }: { t: TFunction; refusal: HakedisRefusal; testId?: string }) {
  const text = refusalText(t, refusal);
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50/60 px-3 py-2 text-sm dark:border-red-900 dark:bg-red-950/30"
      data-testid={testId}
    >
      <AlertTriangle size={15} className="mt-0.5 shrink-0 text-red-600 dark:text-red-400" aria-hidden="true" />
      <div className="min-w-0">
        <p className="break-words text-content-primary">{text}</p>
        {refusal.message && !text.includes(refusal.message) && (
          <p className="mt-0.5 break-words text-xs text-content-secondary">{refusal.message}</p>
        )}
      </div>
    </div>
  );
}

export const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
