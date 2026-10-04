// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A small outlined chip that links to the record next in the workflow, and the
 * "Related:" strip that holds a row of them.
 *
 * The chip is a real `<Link>`, not a button calling `navigate`, so the reader
 * can open it in a new tab, the target shows on hover, and a test can read
 * the destination off the `href`. Its look is the one the contract drawer's
 * related strip already used, lifted here so the tender, bid, change-order
 * and progress screens draw the same chip for the same job.
 */

import { Children, type ReactNode } from 'react';
import { Link } from 'react-router-dom';

const CHIP_CLASS =
  'inline-flex items-center gap-1 rounded-md border border-border-light px-2 py-1 text-xs text-content-secondary hover:text-oe-blue hover:border-oe-blue transition-colors';

export interface RelatedRecordLinkProps {
  to: string;
  icon?: ReactNode;
  title?: string;
  children: ReactNode;
  'data-testid'?: string;
}

export function RelatedRecordLink({ to, icon, title, children, ...rest }: RelatedRecordLinkProps) {
  return (
    <Link to={to} title={title} className={CHIP_CLASS} data-testid={rest['data-testid']}>
      {icon}
      <span className="truncate max-w-[16rem]">{children}</span>
    </Link>
  );
}

export interface RelatedRecordStripProps {
  label: ReactNode;
  children: ReactNode;
  className?: string;
  'data-testid'?: string;
}

/** A labelled row of related-record chips. Renders nothing without children. */
export function RelatedRecordStrip({ label, children, className, ...rest }: RelatedRecordStripProps) {
  // toArray flattens mapped lists and drops false/null, so a strip whose
  // every chip is conditional and absent draws no orphan label.
  if (Children.toArray(children).length === 0) return null;
  return (
    <div
      className={`flex flex-wrap items-center gap-2 text-xs ${className ?? ''}`}
      data-testid={rest['data-testid']}
    >
      <span className="text-content-tertiary">{label}</span>
      {children}
    </div>
  );
}
