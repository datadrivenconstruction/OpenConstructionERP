import { Link } from 'react-router-dom';
import { ChevronRight, Home } from 'lucide-react';
import clsx from 'clsx';

export interface BreadcrumbItem {
  label: string;
  to?: string;
}

interface BreadcrumbProps {
  items: BreadcrumbItem[];
  className?: string;
}

export function Breadcrumb({ items, className }: BreadcrumbProps) {
  if (items.length === 0) return null;

  return (
    <nav aria-label="Breadcrumb" className={clsx('flex items-center gap-1 text-xs', className)}>
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
          <span key={item.label} className="flex items-center gap-1">
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
