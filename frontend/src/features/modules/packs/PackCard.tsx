// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { Boxes, Check, ChevronRight, FolderKanban, Languages, Power } from 'lucide-react';
import { Button } from '@/shared/ui';
import { PackEmblem } from '@/shared/ui/PackEmblem';
import { packNameSlug, packSummary } from '@/shared/lib/regionalPack';
import type { PackEntry } from './packCatalog';
import { PACK_TYPE_META } from './packLabels';

export interface PackCardProps {
  entry: PackEntry;
  isActive: boolean;
  /** Any pack is pinned by the operator's environment; the UI cannot switch. */
  envPinned: boolean;
  canInstall: boolean;
  regionLabel: string;
  languageName: (code: string) => string | null;
  /** Where the detail page's "All packs" link returns to. */
  backTo: string;
  onActivate: (entry: PackEntry) => void;
  onDeactivate: (entry: PackEntry) => void;
}

/** How many standards a card names before it says "+N". */
const STANDARDS_ON_CARD = 3;

function PackCardImpl({
  entry,
  isActive,
  envPinned,
  canInstall,
  regionLabel,
  languageName,
  backTo,
  onActivate,
  onDeactivate,
}: PackCardProps) {
  const { t } = useTranslation();
  const { pack } = entry;
  const meta = PACK_TYPE_META[entry.type];
  const TypeIcon = meta.icon;
  // One line, not the whole paragraph: see packSummary for why the split is on
  // the colon rather than a CSS clamp.
  const summary = packSummary(
    t(`modules.pp_desc_${packNameSlug(pack.slug)}`, { defaultValue: pack.description }),
  );
  const languages = entry.languages.map((l) => languageName(l) ?? l.toUpperCase());
  const extraStandards = entry.standards.length - STANDARDS_ON_CARD;
  const detailHref = `/packs/${encodeURIComponent(pack.slug)}`;

  let action: React.ReactNode = null;
  if (canInstall && !envPinned) {
    action = isActive ? (
      <Button
        variant="secondary"
        size="sm"
        icon={<Power size={14} />}
        onClick={() => onDeactivate(entry)}
        className="relative z-10"
      >
        {t('modules.pack_deactivate', { defaultValue: 'Deactivate' })}
      </Button>
    ) : (
      <Button
        variant="primary"
        size="sm"
        icon={<Power size={14} />}
        onClick={() => onActivate(entry)}
        className="relative z-10"
        aria-label={t('packs.activate_named', { defaultValue: 'Activate {{name}}', name: entry.name })}
      >
        {t('packs.activate', { defaultValue: 'Activate' })}
      </Button>
    );
  }

  return (
    <article
      data-pack-slug={pack.slug}
      id={`pack-card-${pack.slug}`}
      className={clsx(
        'group relative flex h-full flex-col overflow-hidden rounded-xl border bg-surface-elevated p-4 shadow-xs',
        'transition-[box-shadow,border-color,transform] duration-normal ease-oe',
        'hover:-translate-y-0.5 hover:shadow-md motion-reduce:hover:translate-y-0',
        'focus-within:ring-2 focus-within:ring-oe-blue/30',
        isActive ? 'border-semantic-success/50 ring-1 ring-semantic-success/30' : 'border-border-light hover:border-border',
      )}
    >
      {/* Brand accent, on the reading edge in either direction. */}
      <span
        aria-hidden
        className="absolute inset-y-0 start-0 w-1"
        style={{ backgroundColor: pack.branding.primary_color }}
      />

      <div className="flex items-start gap-3">
        <PackEmblem pack={pack} size={44} />
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-semibold leading-snug text-content-primary">
            {/* The whole card is the link to the pack's page; the action
                button sits above the stretched area. */}
            <Link
              to={detailHref}
              state={{ backTo }}
              className="rounded-sm after:absolute after:inset-0 after:content-[''] focus-visible:outline-none"
            >
              {t(`modules.pp_name_${packNameSlug(pack.slug)}`, { defaultValue: pack.partner_name })}
            </Link>
          </h3>
          <p className="mt-0.5 truncate text-xs text-content-tertiary">
            {entry.countryName ? `${entry.countryName} · ${regionLabel}` : regionLabel}
          </p>
        </div>
        {isActive && (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-semantic-success-bg px-2 py-0.5 text-2xs font-semibold text-semantic-success">
            <Check size={11} aria-hidden />
            {t('modules.active', { defaultValue: 'Active' })}
          </span>
        )}
      </div>

      {summary && (
        <p className="mt-3 line-clamp-2 text-xs leading-relaxed text-content-secondary">{summary}</p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <span
          className="inline-flex h-5 items-center gap-1 rounded-md bg-surface-secondary px-1.5 text-2xs font-semibold uppercase tracking-wide text-content-secondary"
        >
          <TypeIcon size={11} aria-hidden style={{ color: pack.branding.accent_color ?? pack.branding.primary_color }} />
          {t(meta.labelKey, { defaultValue: meta.defaultLabel })}
        </span>
        <span
          className="inline-flex h-5 items-center rounded-md bg-surface-secondary px-1.5 font-mono text-2xs font-medium text-content-secondary"
          title={t('packs.currency', { defaultValue: 'Currency' })}
        >
          {pack.default_currency}
        </span>
        {entry.standards.slice(0, STANDARDS_ON_CARD).map((std) => (
          <span
            key={std}
            className="inline-flex h-5 items-center rounded-md border border-border-light px-1.5 text-2xs font-medium text-content-secondary"
          >
            {std}
          </span>
        ))}
        {extraStandards > 0 && (
          <span
            className="inline-flex h-5 items-center rounded-md border border-border-light px-1.5 text-2xs text-content-tertiary"
            title={entry.standards.slice(STANDARDS_ON_CARD).join(', ')}
          >
            +{extraStandards}
          </span>
        )}
      </div>

      <dl className="mt-3 grid grid-cols-1 gap-1 text-2xs text-content-tertiary">
        {languages.length > 0 && (
          <div className="flex min-w-0 items-center gap-1.5">
            <dt>
              <Languages size={12} aria-hidden />
              <span className="sr-only">{t('packs.languages', { defaultValue: 'Languages' })}</span>
            </dt>
            <dd className="truncate">{languages.join(', ')}</dd>
          </div>
        )}
        <div className="flex min-w-0 items-center gap-1.5">
          <dt>
            <Boxes size={12} aria-hidden />
            <span className="sr-only">{t('packs.modules', { defaultValue: 'Modules' })}</span>
          </dt>
          <dd className="truncate">
            {entry.moduleCount === null
              ? t('packs.modules_all', { defaultValue: 'Keeps all modules' })
              : t('packs.modules_n', { defaultValue: 'Modules: {{n}}', n: entry.moduleCount })}
          </dd>
        </div>
        {entry.demoCount > 0 && (
          <div className="flex min-w-0 items-center gap-1.5">
            <dt>
              <FolderKanban size={12} aria-hidden />
              <span className="sr-only">{t('packs.demo_projects', { defaultValue: 'Demo projects' })}</span>
            </dt>
            <dd className="truncate">
              {t('packs.demo_n', { defaultValue: 'Demo projects: {{n}}', n: entry.demoCount })}
            </dd>
          </div>
        )}
      </dl>

      <div className="mt-auto flex items-center justify-between gap-2 pt-4">
        <span className="inline-flex items-center gap-0.5 text-xs font-medium text-oe-blue opacity-80 transition-opacity group-hover:opacity-100">
          {t('packs.details', { defaultValue: 'Details' })}
          <ChevronRight size={14} aria-hidden className="rtl:rotate-180" />
        </span>
        {action}
      </div>
    </article>
  );
}

export const PackCard = memo(PackCardImpl);
