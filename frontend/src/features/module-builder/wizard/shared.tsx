// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Small pieces the wizard's screens share: the problem list, the icon for a
 * field type, the module's own icon, and a disclosure row.
 */
import type { ReactNode } from 'react';
import {
  AlertTriangle,
  AlignLeft,
  Banknote,
  Boxes,
  Calendar,
  CheckSquare,
  ChevronDown,
  Clock,
  CloudSun,
  FileCheck,
  HardHat,
  Hash,
  Layers,
  Link2,
  List,
  Ruler,
  Truck,
  Type,
  type LucideIcon,
} from 'lucide-react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';

import type { ModuleFieldType } from '../api';
import { PROBLEM_TEXT, type SpecProblem } from '../draft';

export function ProblemList({ problems, testId }: { problems: SpecProblem[]; testId?: string }) {
  const { t } = useTranslation();
  if (problems.length === 0) return null;
  return (
    <ul
      className="space-y-1 rounded-lg bg-semantic-warning-bg px-3 py-2 text-xs text-semantic-warning"
      data-testid={testId}
    >
      {problems.map((problem, i) => (
        <li key={`${problem.where}-${i}`} className="flex items-start gap-1.5">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          {t(`module_builder.problem.${problem.code}`, {
            ...problem.params,
            defaultValue: PROBLEM_TEXT[problem.code],
          })}
        </li>
      ))}
    </ul>
  );
}

const TYPE_ICONS: Record<ModuleFieldType, LucideIcon> = {
  text: Type,
  long_text: AlignLeft,
  integer: Hash,
  number: Ruler,
  money: Banknote,
  date: Calendar,
  datetime: Clock,
  boolean: CheckSquare,
  select: List,
  link: Link2,
};

export function FieldTypeIcon({ type, size = 13, className }: { type: ModuleFieldType; size?: number; className?: string }) {
  const Icon = TYPE_ICONS[type] ?? Type;
  return <Icon size={size} aria-hidden className={className} />;
}

/** The icons templates use, by the name stored in the spec. Anything else is the generic box. */
const MODULE_ICONS: Record<string, LucideIcon> = {
  Layers,
  FileCheck,
  Ruler,
  Truck,
  CloudSun,
  HardHat,
  Boxes,
};

export function ModuleIcon({ name, size = 22 }: { name: string; size?: number }) {
  const Icon = MODULE_ICONS[name] ?? Boxes;
  return <Icon size={size} strokeWidth={1.8} aria-hidden />;
}

/**
 * A row that opens and closes the section under it. Used for "Fine-tune",
 * "Advanced" and "What will be created": things that are there for the person
 * who wants them and out of the way of everyone else.
 */
export function Disclosure({
  open,
  onToggle,
  title,
  hint,
  icon,
  testId,
  children,
}: {
  open: boolean;
  onToggle: () => void;
  title: string;
  hint?: string;
  icon?: ReactNode;
  testId?: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-border-light">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        data-testid={testId}
        className="flex w-full items-center gap-2.5 rounded-xl px-4 py-3 text-start transition-colors hover:bg-surface-secondary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
      >
        {icon && <span className="shrink-0 text-content-tertiary">{icon}</span>}
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-content-primary">{title}</span>
          {hint && <span className="block text-xs text-content-tertiary">{hint}</span>}
        </span>
        <ChevronDown
          size={16}
          aria-hidden
          className={clsx('shrink-0 text-content-tertiary transition-transform', open && 'rotate-180')}
        />
      </button>
      {open && <div className="space-y-4 border-t border-border-light px-4 py-4">{children}</div>}
    </div>
  );
}

/** A small uppercase heading over a group on a screen. */
export function SectionHeading({ children, icon }: { children: ReactNode; icon?: ReactNode }) {
  return (
    <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
      {icon}
      {children}
    </p>
  );
}
