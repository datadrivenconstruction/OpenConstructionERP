// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Segmented control switching between Global / Project / Development
 * scopes of the Geo Hub.
 *
 * Routing-aware — clicking a mode navigates via react-router and
 * preserves any contextual ids (active project / development). The
 * caller passes a per-page ``current`` so this component does not
 * have to know its mounting route.
 *
 * UX rule: a tab without context is NEVER inert. Clicking Project
 * with no active project opens an in-page picker dialog so the user
 * stays inside /geo instead of being dumped out into ``/projects``
 * or ``/property-dev``. Visually they are dimmed (``aria-disabled``)
 * with an explanatory tooltip + helper icon. ``aria-disabled`` (rather
 * than the ``disabled`` HTML attribute) keeps them keyboard-focusable
 * per WAI-ARIA tabs pattern.
 *
 * Keeps the bespoke segmented-pill styling so it matches the rest of
 * the Geo Hub toolbar; uses {@link useTabKeyboardNav} for ArrowLeft /
 * Right / Home / End nav + roving tabIndex.
 */

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Globe2, Building2, Boxes, X } from 'lucide-react';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import { apiGet } from '@/shared/lib/api';

export type GeoMode = 'global' | 'project' | 'development';

interface GeoModePickerProps {
  current: GeoMode;
  projectId?: string | null;
  developmentId?: string | null;
}

const ICONS = {
  global: Globe2,
  project: Building2,
  development: Boxes,
} as const;

const GEO_MODES: readonly GeoMode[] = ['global', 'project', 'development'];

type PickerKind = 'project' | 'development';

interface PickerItem {
  id: string;
  name: string;
  subtitle?: string | null;
}

export function GeoModePicker({
  current,
  projectId,
  developmentId,
}: GeoModePickerProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [pickerKind, setPickerKind] = useState<PickerKind | null>(null);

  const items: Array<{
    key: GeoMode;
    label: string;
    description: string;
    href: string | null;
    softDisabled: boolean;
  }> = [
    {
      key: 'global',
      label: t('geo_hub.mode.global', { defaultValue: 'Global' }),
      description: t('geo_hub.mode.global_hint', {
        defaultValue: 'All projects on one earth-scale map.',
      }),
      href: '/geo',
      softDisabled: false,
    },
    {
      key: 'project',
      label: t('geo_hub.mode.project', { defaultValue: 'Project' }),
      description: projectId
        ? t('geo_hub.mode.project_hint', {
            defaultValue: 'Drop into a project — anchor, tilesets, viewpoints.',
          })
        : t('geo_hub.mode.project_hint_disabled', {
            defaultValue: 'Open a project first to enable. Click to pick one.',
          }),
      href: projectId ? `/projects/${projectId}/geo` : null,
      softDisabled: !projectId,
    },
    {
      key: 'development',
      label: t('geo_hub.mode.development', { defaultValue: 'Development' }),
      description: developmentId
        ? t('geo_hub.mode.development_hint', {
            defaultValue: 'Per-development map (PropDev only).',
          })
        : t('geo_hub.mode.development_hint_disabled', {
            defaultValue:
              'Open a development first to enable. Click to pick one.',
          }),
      href: developmentId
        ? `/property-dev/developments/${developmentId}/geo`
        : null,
      softDisabled: !developmentId,
    },
  ];

  const handleClick = (it: (typeof items)[number]) => {
    if (it.key === current) return;
    if (it.softDisabled) {
      // Open in-page picker instead of dumping the user out of /geo.
      setPickerKind(it.key === 'project' ? 'project' : 'development');
      return;
    }
    if (it.href) navigate(it.href);
  };

  const onTabKeyDown = useTabKeyboardNav<GeoMode>({
    ids: GEO_MODES,
    activeId: current,
    onChange: (next) => {
      const item = items.find((it) => it.key === next);
      if (item) handleClick(item);
    },
    orientation: 'horizontal',
  });

  const handlePicked = (kind: PickerKind, id: string) => {
    setPickerKind(null);
    if (kind === 'project') {
      navigate(`/projects/${id}/geo`);
    } else {
      navigate(`/property-dev/developments/${id}/geo`);
    }
  };

  return (
    <>
      <div
        className={[
          'inline-flex items-center gap-0.5 rounded-lg border border-border',
          'bg-surface-primary p-0.5 shadow-xs',
        ].join(' ')}
        role="tablist"
        aria-label={t('geo_hub.mode.tablist_label', { defaultValue: 'Map scope' })}
        onKeyDown={onTabKeyDown}
        data-testid="geo-tour-mode-picker"
      >
        {items.map((it) => {
          const active = it.key === current;
          const Icon = ICONS[it.key];
          return (
            <button
              key={it.key}
              type="button"
              role="tab"
              id={`geo-hub-mode-tab-${it.key}`}
              aria-selected={active}
              aria-controls={`geo-hub-mode-panel-${it.key}`}
              tabIndex={active ? 0 : -1}
              aria-disabled={it.softDisabled || undefined}
              title={it.description}
              onClick={() => handleClick(it)}
              className={[
                'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium',
                'transition-colors duration-fast ease-oe',
                active
                  ? 'bg-content-primary text-content-inverse shadow-sm'
                  : it.softDisabled
                    ? 'text-content-quaternary hover:bg-surface-secondary hover:text-content-tertiary'
                    : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
              ].join(' ')}
              data-testid={`geo-mode-tab-${it.key}`}
            >
              <Icon size={13} strokeWidth={2} />
              {it.label}
              {it.softDisabled && (
                <span
                  aria-hidden
                  className="ml-0.5 inline-flex h-3.5 w-3.5 items-center justify-center rounded-full bg-amber-400/20 text-[9px] font-bold leading-none text-amber-700 ring-1 ring-amber-400/40 dark:text-amber-300"
                  title={it.description}
                >
                  ?
                </span>
              )}
            </button>
          );
        })}
      </div>
      {pickerKind && (
        <ContextPickerDialog
          kind={pickerKind}
          onClose={() => setPickerKind(null)}
          onPick={(id) => handlePicked(pickerKind, id)}
        />
      )}
    </>
  );
}

interface ContextPickerDialogProps {
  kind: PickerKind;
  onClose: () => void;
  onPick: (id: string) => void;
}

function ContextPickerDialog({ kind, onClose, onPick }: ContextPickerDialogProps) {
  const { t } = useTranslation();
  const [items, setItems] = useState<PickerItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setItems(null);
    const load = async () => {
      try {
        if (kind === 'project') {
          const rows = await apiGet<Array<{ id: string; name: string; status?: string }>>(
            '/v1/projects/',
          );
          if (cancelled) return;
          setItems(
            rows.map((r) => ({ id: r.id, name: r.name, subtitle: r.status ?? null })),
          );
        } else {
          const rows = await apiGet<
            Array<{ id: string; name: string; city?: string | null; country_code?: string | null }>
          >('/v1/property-dev/developments/');
          if (cancelled) return;
          setItems(
            rows.map((r) => ({
              id: r.id,
              name: r.name,
              subtitle:
                [r.city, r.country_code?.toUpperCase()].filter(Boolean).join(', ') || null,
            })),
          );
        }
      } catch {
        if (!cancelled) {
          setError(
            t('geo_hub.picker.load_error', {
              defaultValue: 'Could not load list. Try again.',
            }),
          );
        }
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [kind, t]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const title =
    kind === 'project'
      ? t('geo_hub.picker.project_title', { defaultValue: 'Open project on map' })
      : t('geo_hub.picker.development_title', {
          defaultValue: 'Open development on map',
        });
  const emptyText =
    kind === 'project'
      ? t('geo_hub.picker.project_empty', {
          defaultValue: 'No projects yet. Create one from the Projects page.',
        })
      : t('geo_hub.picker.development_empty', {
          defaultValue: 'No developments yet. Create one from Property Developments.',
        });

  const q = query.trim().toLowerCase();
  const filtered =
    items && q
      ? items.filter(
          (i) =>
            i.name.toLowerCase().includes(q) ||
            (i.subtitle ?? '').toLowerCase().includes(q),
        )
      : items;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onClose}
      data-testid="geo-context-picker-backdrop"
    >
      <div
        className="w-full max-w-md rounded-xl border border-border bg-surface-primary shadow-xl"
        onClick={(e) => e.stopPropagation()}
        data-testid="geo-context-picker-dialog"
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold text-content-primary">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
            data-testid="geo-context-picker-close"
          >
            <X size={16} strokeWidth={2} />
          </button>
        </div>
        <div className="border-b border-border px-4 py-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('geo_hub.picker.search_placeholder', {
              defaultValue: 'Search…',
            })}
            autoFocus
            className={[
              'h-9 w-full rounded-md border border-border bg-surface-primary',
              'px-3 text-sm text-content-primary placeholder:text-content-tertiary',
              'focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent',
            ].join(' ')}
            data-testid="geo-context-picker-search"
          />
        </div>
        <div className="max-h-80 overflow-y-auto">
          {error && (
            <div className="px-4 py-6 text-sm text-content-secondary">{error}</div>
          )}
          {!error && items === null && (
            <div className="px-4 py-6 text-sm text-content-tertiary">
              {t('common.loading', { defaultValue: 'Loading…' })}
            </div>
          )}
          {!error && items && filtered && filtered.length === 0 && (
            <div className="px-4 py-6 text-sm text-content-tertiary">
              {items.length === 0
                ? emptyText
                : t('geo_hub.picker.no_matches', {
                    defaultValue: 'No matches.',
                  })}
            </div>
          )}
          {!error && filtered && filtered.length > 0 && (
            <ul className="py-1">
              {filtered.map((it) => (
                <li key={it.id}>
                  <button
                    type="button"
                    onClick={() => onPick(it.id)}
                    className={[
                      'flex w-full items-start gap-2 px-4 py-2 text-left',
                      'text-sm text-content-primary hover:bg-surface-secondary',
                    ].join(' ')}
                    data-testid="geo-context-picker-item"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{it.name}</div>
                      {it.subtitle && (
                        <div className="mt-0.5 truncate text-xs text-content-tertiary">
                          {it.subtitle}
                        </div>
                      )}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

export default GeoModePicker;
