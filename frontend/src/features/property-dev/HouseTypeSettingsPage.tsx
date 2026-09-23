// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * House-type catalogue settings.
 *
 * CRUD over user-created entries in /property-dev/house-type-catalogue/.
 * Presets are listed read-only (no edit / delete) so the operator can see
 * the full inventory but can't accidentally wipe shipped defaults.
 *
 * The "New / Edit house type" modal is intentionally polished - it
 * is the only path through which a tenant exposes their domain
 * vocabulary to the rest of the app, so a clean, dense, validated form
 * makes a disproportionate UX impact. See <HouseTypeEditModal>.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Building2, Globe2, Pencil, Plus, Trash2 } from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  ConfirmDialog,
  CountryFlag,
  EmptyState,
  SkeletonTable,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useDisplayQuantity } from '@/shared/hooks/useDisplayQuantity';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { getCountry } from '@/shared/lib/countries';
import {
  deleteHouseTypeCatalogue,
  fetchHouseTypes,
  type HouseTypeCatalogueEntry,
} from './api';
import { HouseTypeEditModal } from './HouseTypeEditModal';
import { fmtFixed } from '@/shared/lib/formatters';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const labelCls = 'block text-xs font-medium text-content-secondary mb-1';

export interface ProjectStub {
  id: string;
  name: string;
}

function listProjectsLite(): Promise<ProjectStub[]> {
  return fetchProjectList<ProjectStub[]>().catch(
    () => [] as ProjectStub[],
  );
}

/** Short country list used only by the top-of-page filter (not the
 *  modal - the modal uses the full searchable picker). */
const FILTER_COUNTRY_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'All / global' },
  { value: 'DE', label: 'Deutschland (DE)' },
  { value: 'US', label: 'United States (US)' },
  { value: 'GB', label: 'United Kingdom (GB)' },
  { value: 'RU', label: 'Россия (RU)' },
  { value: 'TR', label: 'Türkiye (TR)' },
  { value: 'FR', label: 'France (FR)' },
  { value: 'ES', label: 'España (ES)' },
  { value: 'IT', label: 'Italia (IT)' },
  { value: 'PL', label: 'Polska (PL)' },
  { value: 'JP', label: '日本 (JP)' },
  { value: 'CN', label: '中国 (CN)' },
  { value: 'SA', label: 'السعودية (SA)' },
];

export function HouseTypeSettingsPage() {
  const { t } = useTranslation();
  const dq = useDisplayQuantity();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [filterCountry, setFilterCountry] = useState('');
  const [filterProject, setFilterProject] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<HouseTypeCatalogueEntry | null>(null);
  const [pendingDelete, setPendingDelete] = useState<HouseTypeCatalogueEntry | null>(null);

  const projectsQ = useQuery({
    queryKey: ['propdev', 'house-type-settings', 'projects-lite'],
    queryFn: listProjectsLite,
    staleTime: 60_000,
  });
  const projects = projectsQ.data ?? [];

  const listQ = useQuery({
    queryKey: [
      'propdev',
      'house-type-catalogue',
      filterCountry || 'all',
      filterProject || 'none',
    ],
    queryFn: () =>
      fetchHouseTypes(filterCountry || undefined, filterProject || undefined),
  });
  const rows = listQ.data ?? [];

  const presets = useMemo(() => rows.filter((r) => r.is_preset), [rows]);
  const customs = useMemo(() => rows.filter((r) => !r.is_preset), [rows]);

  const deleteMu = useMutation({
    mutationFn: (id: string) => deleteHouseTypeCatalogue(id),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('property_dev.house_type.deleted', {
          defaultValue: 'House type deleted',
        }),
      });
      qc.invalidateQueries({ queryKey: ['propdev', 'house-type-catalogue'] });
    },
    onError: (err) => {
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.settings', { defaultValue: 'Settings' }) },
          {
            label: t('nav.property_dev', { defaultValue: 'Property Development' }),
            to: '/property-dev',
          },
          {
            label: t('property_dev.house_type.settings_title', {
              defaultValue: 'House types',
            }),
          },
        ]}
      />

      <PageHeader
        srTitle={t('property_dev.house_type.settings_title', {
          defaultValue: 'House type catalogue',
        })}
        subtitle={t('property_dev.house_type.settings_desc', {
          defaultValue:
            'Country-scoped presets plus your custom entries. Presets are read-only; custom entries are scoped to one project.',
        })}
        actions={
          <Button
            variant="primary"
            icon={<Plus size={14} />}
            onClick={() => {
              setEditing(null);
              setModalOpen(true);
            }}
            disabled={projects.length === 0}
          >
            {t('property_dev.house_type.new', { defaultValue: 'New house type' })}
          </Button>
        }
      />

      <Card className="p-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className={labelCls}>
              <Globe2 size={12} className="mr-1 inline" />
              {t('property_dev.house_type.country_label', {
                defaultValue: 'Country',
              })}
            </label>
            <select
              value={filterCountry}
              onChange={(e) => setFilterCountry(e.target.value)}
              className={inputCls}
            >
              {FILTER_COUNTRY_OPTIONS.map((c) => (
                <option key={c.value || '_all_'} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelCls}>
              <Building2 size={12} className="mr-1 inline" />
              {t('property_dev.house_type.project_filter_label', {
                defaultValue: 'Project (for custom entries)',
              })}
            </label>
            <select
              value={filterProject}
              onChange={(e) => setFilterProject(e.target.value)}
              className={inputCls}
            >
              <option value="">
                {t('common.none', { defaultValue: 'None' })}
              </option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </Card>

      {listQ.isLoading ? (
        <SkeletonTable rows={6} />
      ) : listQ.isError ? (
        <Card padding="md">
          <EmptyState
            title={t('property_dev.house_type.load_error_title', {
              defaultValue: 'Could not load house types',
            })}
            description={
              listQ.error instanceof Error
                ? listQ.error.message
                : t('common.unknown_error', {
                    defaultValue: 'An unknown error occurred.',
                  })
            }
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => listQ.refetch(),
            }}
          />
        </Card>
      ) : rows.length === 0 ? (
        <EmptyState
          title={t('property_dev.house_type.empty_title', {
            defaultValue: 'No house types yet',
          })}
          description={t('property_dev.house_type.empty_desc', {
            defaultValue:
              'House types are reusable unit templates (3-bed terrace, 1-bed apartment, etc.). Pick a country to load presets, or create a custom one.',
          })}
          action={
            projects.length > 0
              ? {
                  label: t('property_dev.house_type.new', {
                    defaultValue: 'New house type',
                  }),
                  onClick: () => {
                    setEditing(null);
                    setModalOpen(true);
                  },
                }
              : undefined
          }
        />
      ) : (
        <>
          {customs.length > 0 && (
            <Card className="overflow-hidden">
              <header className="border-b border-border-light bg-surface-secondary px-4 py-2">
                <h2 className="text-sm font-semibold text-content-primary">
                  {t('property_dev.house_type.custom_section', {
                    defaultValue: 'Your custom entries',
                  })}
                </h2>
              </header>
              <table className="w-full text-sm">
                <thead className="bg-surface-secondary text-xs uppercase text-content-tertiary">
                  <tr>
                    <th className="px-3 py-2 text-left">
                      {t('property_dev.house_type.code_label', { defaultValue: 'Code' })}
                    </th>
                    <th className="px-3 py-2 text-left">
                      {t('property_dev.house_type.name_label', { defaultValue: 'Name' })}
                    </th>
                    <th className="px-3 py-2 text-left">
                      {t('property_dev.house_type.country_label', {
                        defaultValue: 'Country',
                      })}
                    </th>
                    <th className="px-3 py-2 text-right">
                      {t('common.actions', { defaultValue: 'Actions' })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {customs.map((entry) => (
                    <tr
                      key={entry.id}
                      className="border-t border-border-light"
                    >
                      <td className="px-3 py-2 font-mono text-xs text-content-secondary">
                        {entry.code}
                      </td>
                      <td className="px-3 py-2 text-content-primary">{entry.name}</td>
                      <td className="px-3 py-2">
                        <CountryCell entry={entry} />
                      </td>
                      <td className="px-3 py-2 text-right">
                        <div className="inline-flex gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            icon={<Pencil size={12} />}
                            onClick={() => {
                              setEditing(entry);
                              setModalOpen(true);
                            }}
                          >
                            {t('common.edit', { defaultValue: 'Edit' })}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            icon={<Trash2 size={12} />}
                            onClick={() => setPendingDelete(entry)}
                          >
                            {t('common.delete', { defaultValue: 'Delete' })}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
          <Card className="overflow-hidden">
            <header className="border-b border-border-light bg-surface-secondary px-4 py-2">
              <h2 className="text-sm font-semibold text-content-primary">
                {t('property_dev.house_type.preset_section', {
                  defaultValue: 'Shipped presets (read-only)',
                })}
              </h2>
            </header>
            <table className="w-full text-sm">
              <thead className="bg-surface-secondary text-xs uppercase text-content-tertiary">
                <tr>
                  <th className="px-3 py-2 text-left">
                    {t('property_dev.house_type.code_label', { defaultValue: 'Code' })}
                  </th>
                  <th className="px-3 py-2 text-left">
                    {t('property_dev.house_type.name_label', { defaultValue: 'Name' })}
                  </th>
                  <th className="px-3 py-2 text-left">
                    {t('property_dev.house_type.country_label', {
                      defaultValue: 'Country',
                    })}
                  </th>
                  <th className="px-3 py-2 text-left">
                    {t('property_dev.house_type.area_typical_col', {
                      defaultValue: 'Typical {{unit}}',
                      unit: dq.unitFor('m²'),
                    })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {presets.map((entry) => (
                  <tr key={entry.id} className="border-t border-border-light">
                    <td className="px-3 py-2 font-mono text-xs text-content-secondary">
                      {entry.code}
                    </td>
                    <td className="px-3 py-2 text-content-primary">{entry.name}</td>
                    <td className="px-3 py-2">
                      <CountryCell entry={entry} variant="neutral" />
                    </td>
                    <td className="px-3 py-2 text-content-secondary">
                      {entry.area_typical_m2 == null
                        ? '—'
                        : dq.system === 'imperial' &&
                            Number.isFinite(Number(entry.area_typical_m2))
                          ? (() => {
                              const a = dq.convert(
                                Number(entry.area_typical_m2),
                                'm²',
                              );
                              return `${fmtFixed(a.value, 1)} ${a.unit}`;
                            })()
                          : entry.area_typical_m2}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}

      {modalOpen && (
        <HouseTypeEditModal
          entry={editing}
          projects={projects}
          onClose={() => {
            setModalOpen(false);
            setEditing(null);
          }}
        />
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        loading={deleteMu.isPending}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => {
          if (!pendingDelete) return;
          const id = pendingDelete.id;
          setPendingDelete(null);
          deleteMu.mutate(id);
        }}
        title={t('property_dev.house_type.confirm_delete_title', {
          defaultValue: 'Delete house type "{{name}}"?',
          name: pendingDelete?.name ?? '',
        })}
        message={t('property_dev.house_type.confirm_delete', {
          defaultValue:
            'Delete this house type? Plots already using it keep their stored label. This cannot be undone.',
        })}
      />
    </div>
  );
}

function CountryCell({
  entry,
  variant = 'blue',
}: {
  entry: HouseTypeCatalogueEntry;
  variant?: 'blue' | 'neutral';
}) {
  if (entry.region_label && !entry.country_code) {
    return <Badge variant={variant}>{entry.region_label}</Badge>;
  }
  if (entry.country_code) {
    const c = getCountry(entry.country_code);
    return (
      <span className="inline-flex items-center gap-1.5">
        <CountryFlag code={entry.country_code} size={16} />
        <Badge variant={variant}>{entry.country_code}</Badge>
        {c && <span className="text-xs text-content-tertiary">{c.name}</span>}
      </span>
    );
  }
  return <span className="text-content-tertiary">—</span>;
}
