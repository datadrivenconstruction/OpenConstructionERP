// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { Link } from 'react-router-dom';
import { ChevronRight, Home } from 'lucide-react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';

export interface BreadcrumbItem {
  label: string;
  to?: string;
}

interface BreadcrumbProps {
  items: BreadcrumbItem[];
  className?: string;
}

export function Breadcrumb({ items, className }: BreadcrumbProps) {
  const { t } = useTranslation();
  // A single-item trail (just the module label) duplicates the top app bar,
  // which already shows the active module icon + name next to the project
  // selector. Founder decision 2026-06-06 (MODULE_STYLE_GUIDE section 2.1):
  // breadcrumbs render only when they add depth - a project link or a
  // detail trail. Top-level module pages therefore render nothing here.
  if (items.length <= 1) return null;

  return (
    <nav aria-label={t('common.breadcrumb', { defaultValue: 'Breadcrumb' })} className={clsx('flex flex-wrap items-center gap-1 text-xs min-w-0', className)}>
      <Link
        to="/"
        className="flex items-center text-content-tertiary hover:text-content-secondary transition-colors"
        aria-label="Dashboard"
      >
        <Home size={13} />
      </Link>
      {items.map((item, idx) => {
        const isLast = idx === items.length - 1;
        return (
          <span key={item.label} className="flex items-center gap-1 min-w-0">
            <ChevronRight size={12} className="text-content-quaternary" />
            {isLast || !item.to ? (
              <span className="text-content-primary font-medium truncate max-w-[200px]">
                {item.label}
              </span>
            ) : (
              <Link
                to={item.to}
                className="text-content-tertiary hover:text-content-secondary transition-colors truncate max-w-[200px]"
              >
                {item.label}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}
