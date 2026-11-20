// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Data paths drawer a module header opens: Flow | List | People for one
// module, the links derived from the code behind "Show all links", and the
// ways out (full view, platform map, export).

import { useId, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Download, ExternalLink, Map as MapIcon, Network, List as ListIcon, Users } from 'lucide-react';

import { SideDrawer } from '@/shared/ui/SideDrawer';
import { TabBar } from '@/shared/ui/TabBar';
import { Button } from '@/shared/ui/Button';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

import { useModulePaths, useProjectParties, type EdgeOut } from './api';
import { buildFlowModel, humanize, listRows, moduleLabel, type FlowModel } from './flowModel';
import { FocusView } from './FocusView';
import { PartiesHoneycomb } from './PartiesHoneycomb';
import { buildCsv, buildFlowSvg, download, svgToPng, themeColors } from './exportDataPaths';
import { useNarrow } from './motion';
import { fmtList } from '@/shared/lib/formatters';

type Tab = 'flow' | 'list' | 'people';

export interface DataPathsDrawerProps {
  module: string;
  open: boolean;
  onClose: () => void;
}

export function DataPathsDrawer({ module, open, onClose }: DataPathsDrawerProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const narrow = useNarrow();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const [tab, setTab] = useState<Tab>(narrow ? 'list' : 'flow');
  const query = useModulePaths(module, projectId, open);
  const parties = useProjectParties(projectId, open && tab === 'people');
  const model = useMemo(() => (query.data ? buildFlowModel(t, query.data) : null), [query.data, t]);
  const descId = useId();
  const title = model?.moduleLabel ?? moduleLabel(t, module);
  const pathModules = useMemo(
    () => new Set([module, ...(model ? [...model.inputs, ...model.outputs].map((c) => c.module) : [])]),
    [module, model],
  );

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      title={t('data_paths.drawer_title', { defaultValue: 'Data paths: {{module}}', module: title })}
      subtitle={
        projectId
          ? t('data_paths.subtitle_project', { defaultValue: 'Live numbers for the current project' })
          : t('data_paths.subtitle_no_project', { defaultValue: 'Pick a project to see live numbers' })
      }
      widthClass={tab === 'flow' ? 'sm:max-w-[min(1440px,96vw)]' : 'sm:max-w-3xl'}
      headerActions={model ? <ExportMenu model={model} /> : null}
    >
      <div className="space-y-4 p-4" data-testid="data-paths-drawer">
        {model?.why && (
          <p id={descId} className="rounded-lg bg-surface-secondary px-3 py-2 text-sm text-content-secondary">
            {model.why}
          </p>
        )}
        <TabBar<Tab>
          tabs={[
            { id: 'flow', label: t('data_paths.tab_flow', { defaultValue: 'Flow' }), icon: <Network size={14} /> },
            { id: 'list', label: t('data_paths.tab_list', { defaultValue: 'List' }), icon: <ListIcon size={14} /> },
            { id: 'people', label: t('data_paths.tab_people', { defaultValue: 'People' }), icon: <Users size={14} /> },
          ]}
          activeId={tab}
          onChange={setTab}
          ariaLabel={t('data_paths.tabs_aria', { defaultValue: 'Data paths views' })}
          idPrefix="data-paths"
          size="sm"
        />
        {query.isLoading && <div className="h-48 animate-pulse rounded-xl bg-surface-secondary" aria-busy="true" />}
        {query.isError && (
          <p className="text-sm text-semantic-error">
            {t('data_paths.load_failed', { defaultValue: 'The data paths could not be loaded.' })}
          </p>
        )}
        {tab === 'flow' && (
          <FocusView
            module={module}
            projectId={projectId}
            enabled={open}
            canvasHeight="max(480px, calc(100vh - 300px))"
            onOpenModule={(route) => {
              onClose();
              navigate(route);
            }}
            onPeople={() => setTab('people')}
          />
        )}
        {model && tab === 'list' && <DataPathsList model={model} />}
        {tab === 'people' && (
          projectId ? (
            parties.data ? (
              // Everyone on the project, with the people who work in this module lit.
              <PartiesHoneycomb
                parties={parties.data.parties}
                litModules={parties.data.parties.some((p) => !p.placeholder && p.modules.includes(module)) ? new Set([module]) : null}
                pathModules={pathModules}
                compact
                wideList
              />
            ) : (
              <div className="h-32 animate-pulse rounded-xl bg-surface-secondary" aria-busy="true" />
            )
          ) : (
            <p className="text-sm text-content-tertiary">
              {t('data_paths.subtitle_no_project', { defaultValue: 'Pick a project to see live numbers' })}
            </p>
          )
        )}
        {query.data && <TechnicalLinks edges={query.data.technical} module={module} />}
        <div className="flex flex-wrap gap-2 border-t border-border-light pt-3">
          <Button
            variant="secondary"
            size="sm"
            icon={<ExternalLink size={14} />}
            onClick={() => {
              onClose();
              navigate(`/data-paths/${encodeURIComponent(module)}`);
            }}
          >
            {t('data_paths.open_full', { defaultValue: 'Open full view' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<MapIcon size={14} />}
            onClick={() => {
              onClose();
              navigate(`/data-paths?focus=${encodeURIComponent(module)}`);
            }}
          >
            {t('data_paths.open_map', { defaultValue: 'Open platform map' })}
          </Button>
        </div>
      </div>
    </SideDrawer>
  );
}

export function DataPathsList({ model }: { model: FlowModel }) {
  const { t } = useTranslation();
  const rows = listRows(model);
  const heads = {
    in: t('data_paths.sources', { defaultValue: 'Sources' }),
    centre: t('data_paths.this_module', { defaultValue: 'This module' }),
    out: t('data_paths.consumers', { defaultValue: 'Consumers' }),
  };
  return (
    <div className="space-y-3" data-testid="dp-list">
      {(['in', 'centre', 'out'] as const).map((section) => {
        const items = rows.filter((r) => r.section === section);
        if (!items.length) return null;
        return (
          <section key={section}>
            <h4 className="mb-1 text-2xs font-medium uppercase tracking-wide text-content-tertiary">{heads[section]}</h4>
            <ul className="divide-y divide-border-light rounded-lg border border-border-light">
              {items.map((r, i) => (
                <li key={`${section}-${i}`} className="px-3 py-2 text-sm text-content-primary">
                  {r.href ? (
                    <Link to={r.href} className="hover:text-oe-blue">
                      {r.text}
                    </Link>
                  ) : (
                    r.text
                  )}
                </li>
              ))}
            </ul>
          </section>
        );
      })}
      {model.params.length > 0 && (
        <section>
          <h4 className="mb-1 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
            {t('data_paths.parameters', { defaultValue: 'Parameters' })}
          </h4>
          <ul className="space-y-1 text-sm text-content-secondary">
            {model.params.map((p) => (
              <li key={p.id}>{p.note}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

const KIND_KEYS: Record<EdgeOut['kind'], [string, string]> = {
  declared: ['data_paths.kind_declared', 'Described'],
  depends: ['data_paths.kind_depends', 'Depends on'],
  fk: ['data_paths.kind_fk', 'Record link'],
  event: ['data_paths.kind_event', 'Event'],
};

function TechnicalLinks({ edges, module }: { edges: EdgeOut[]; module: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const technical = edges.filter((e) => e.kind !== 'declared');
  if (!technical.length) return null;
  return (
    <div className="rounded-lg border border-border-light">
      <button
        type="button"
        className="flex w-full items-center justify-between px-3 py-2 text-start text-sm text-content-secondary hover:bg-surface-secondary"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        data-testid="dp-show-all"
      >
        <span>
          {open
            ? t('data_paths.hide_all_links', { defaultValue: 'Hide technical links' })
            : t('data_paths.show_all_links', { defaultValue: 'Show all links' })}
        </span>
        <span className="tabular-nums text-content-tertiary">{technical.length}</span>
      </button>
      {open && (
        <ul className="divide-y divide-border-light border-t border-border-light text-xs">
          {technical.map((e, i) => {
            const other = e.source === module ? e.target : e.source;
            const [kk, kdef] = KIND_KEYS[e.kind];
            return (
              <li key={`${e.kind}-${e.source}-${e.target}-${i}`} className="flex items-center gap-2 px-3 py-1.5">
                <span className="w-24 shrink-0 text-content-tertiary">{t(kk, { defaultValue: kdef })}</span>
                <span className="text-content-quaternary" aria-hidden>
                  {e.source === module ? '→' : '←'}
                </span>
                <span className="truncate text-content-primary">{moduleLabel(t, other, humanize(other))}</span>
                {e.details.length > 0 && <span className="ms-auto truncate text-content-tertiary">{fmtList(e.details.slice(0, 2))}</span>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function ExportMenu({ model }: { model: FlowModel }) {
  const { t } = useTranslation();
  const base = `data-paths-${model.module.replace(/^oe_/, '')}`;
  const svg = () => buildFlowSvg(model, themeColors());
  const csv = () =>
    buildCsv(
      model,
      {
        section: t('data_paths.csv_section', { defaultValue: 'Section' }),
        text: t('data_paths.csv_text', { defaultValue: 'Data' }),
        link: t('data_paths.csv_link', { defaultValue: 'Link' }),
      },
      {
        in: t('data_paths.sources', { defaultValue: 'Sources' }),
        centre: t('data_paths.this_module', { defaultValue: 'This module' }),
        out: t('data_paths.consumers', { defaultValue: 'Consumers' }),
      },
    );
  const label = t('data_paths.export', { defaultValue: 'Export' });
  return (
    <div className="flex items-center gap-1" role="group" aria-label={label}>
      <Download size={14} className="text-content-tertiary" aria-hidden />
      <Button variant="ghost" size="sm" onClick={() => download(`${base}.svg`, new Blob([svg()], { type: 'image/svg+xml' }))}>
        SVG
      </Button>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          void svgToPng(svg()).then((b) => download(`${base}.png`, b)).catch(() => undefined);
        }}
      >
        PNG
      </Button>
      <Button variant="ghost" size="sm" onClick={() => download(`${base}.csv`, new Blob([csv()], { type: 'text/csv;charset=utf-8' }))}>
        CSV
      </Button>
    </div>
  );
}
