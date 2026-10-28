// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The plant register, mounted at /projects/:projectId/plant-register.
//
// The register is the home view. An item opens in place and the URL remembers
// it (?item=), so a link reopens the same item. The long-lead timeline, the
// delivery limit matrix, site and IT and the frame summary sit behind tabs.

import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useProjectName } from '@/shared/hooks/useProjectName';
import { useParams, useSearchParams } from 'react-router-dom';
import { CalendarClock, Compass, Factory, Grid3x3, ListChecks, Plus, Router } from 'lucide-react';

import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { TabBar } from '@/shared/ui/TabBar';

import { localToday } from './api';
import { DeliveryLimitsMatrix } from './DeliveryLimitsMatrix';
import { FrameSummary } from './FrameSummary';
import {
  useFindings,
  useFrameSummary,
  useInvalidatePlant,
  useItServices,
  useLabelContext,
  useLimitMatrix,
  usePeopleNames,
  usePlantCatalogue,
  usePlantItems,
  usePlantSettings,
  useReadiness,
} from './hooks';
import { ItemDialog } from './ItemDialog';
import { ItemPanel } from './ItemPanel';
import { LongLeadTimeline } from './LongLeadTimeline';
import { PlantCanContext, WriteButton, canOf, refusalText, withheldReason } from './PlantBits';
import { RegisterTable } from './RegisterTable';
import { SiteItPanel } from './SiteItPanel';

type Tab = 'register' | 'long_lead' | 'limits' | 'site_it' | 'frame';

export function PlantRegisterPage() {
  const { t } = useTranslation();
  const { projectId = '' } = useParams<{ projectId: string }>();
  const projectName = useProjectName(projectId);
  const [params, setParams] = useSearchParams();
  const labels = useLabelContext();
  const personName = usePeopleNames(projectId);
  const invalidate = useInvalidatePlant(projectId);
  const [adding, setAdding] = useState(false);

  const tab = (params.get('tab') as Tab | null) ?? 'register';
  const itemId = params.get('item');
  const go = (next: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v === null) p.delete(k);
      else p.set(k, v);
    }
    setParams(p, { replace: false });
  };

  const catalogueQ = usePlantCatalogue(projectId);
  const itemsQ = usePlantItems(projectId);
  const settingsQ = usePlantSettings(projectId);
  const can = canOf(settingsQ.data, settingsQ.isLoading);
  const readOnly = withheldReason(t, can.edit, 'edit_permission_required');
  const mayAdd = !can.pending && readOnly === null && can.edit.applies !== false;
  const loaded = !!catalogueQ.data && !!itemsQ.data;
  const matrixQ = useLimitMatrix(projectId, loaded && tab === 'limits' && !itemId);
  const itQ = useItServices(projectId, loaded && tab === 'site_it' && !itemId);
  const frameQ = useFrameSummary(projectId, loaded && (tab === 'site_it' || tab === 'frame') && !itemId);
  const readinessQ = useReadiness(projectId, loaded && tab === 'frame' && !itemId);
  const findingsQ = useFindings(projectId, loaded && tab === 'frame' && !itemId);

  const header = (
    <>
      <Breadcrumb
        items={[
          { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
          { label: projectName || t('plant.page.project', { defaultValue: 'Project' }), to: `/projects/${projectId}` },
          { label: t('plant.nav.title', { defaultValue: 'Plant register' }) },
        ]}
      />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-content-primary">{t('plant.nav.title', { defaultValue: 'Plant register' })}</h1>
          <p className="text-sm text-content-secondary">
            {t('plant.page.subtitle', {
              defaultValue: 'The plant and equipment the project has to order early, and the latest day each one can be ordered.',
            })}
          </p>
        </div>
        {loaded && !itemId && (itemsQ.data?.items.length ?? 0) > 0 && (
          <WriteButton icon={<Plus size={16} />} onClick={() => setAdding(true)} data-testid="plant-add-item">
            {t('plant.item.add_submit', { defaultValue: 'Add item' })}
          </WriteButton>
        )}
      </div>
      <CollapsibleSection
        storageKey="plant_register.how"
        icon={<Compass className="h-4 w-4" />}
        title={t('plant.page.how_title', { defaultValue: 'How the plant register works' })}
        subtitle={t('plant.page.how_subtitle', { defaultValue: 'Item, lead time, order date, route, handover' })}
      >
        <ol className="ml-4 list-decimal space-y-1 text-sm text-content-secondary">
          <li>{t('plant.page.how_step_1', { defaultValue: 'List every piece of plant that takes long to get: transformers, switchgear, chillers, lifts. Say what it must do and when it is needed on site.' })}</li>
          <li>{t('plant.page.how_step_2', { defaultValue: 'Ask the market for the lead time and record each answer with its date. The register counts back from the need date to the latest day the order can be placed.' })}</li>
          <li>{t('plant.page.how_step_3', { defaultValue: 'Decide who buys and who installs. A critical item needs an approved decision paper, and a very long lead time a reserved production slot.' })}</li>
          <li>{t('plant.page.how_step_4', { defaultValue: 'Follow the item through order, delivery and commissioning, then hand it over to the operator together with its spares.' })}</li>
        </ol>
      </CollapsibleSection>
    </>
  );

  const failed = catalogueQ.error ?? itemsQ.error;
  if (failed) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5">
        {header}
        <ErrorState
          title={t('plant.page.load_failed', { defaultValue: 'The plant register could not be loaded' })}
          hint={refusalText(t, failed)}
          onRetry={() => {
            void catalogueQ.refetch();
            void itemsQ.refetch();
          }}
        />
      </div>
    );
  }
  const catalogue = catalogueQ.data;
  const page = itemsQ.data;
  if (!catalogue || !page) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5">
        {header}
        <SkeletonTable rows={6} columns={7} />
      </div>
    );
  }

  const items = page.items;
  const selected = itemId ? items.find((i) => i.id === itemId) ?? null : null;
  const overdue = items.filter((i) => i.order_status === 'overdue' && i.status !== 'cancelled').length;

  const pending = (q: { isLoading: boolean; error: unknown; refetch: () => unknown }, title: string): ReactNode | null => {
    if (q.error) return <ErrorState title={title} hint={refusalText(t, q.error)} onRetry={() => void q.refetch()} />;
    if (q.isLoading) return <SkeletonTable rows={4} columns={5} />;
    return null;
  };

  let body: ReactNode;
  if (itemId) {
    body = selected ? (
      <ItemPanel
        key={selected.id}
        projectId={projectId}
        item={selected}
        catalogue={catalogue}
        labels={labels}
        personName={personName}
        onBack={() => go({ item: null })}
        onChanged={invalidate}
      />
    ) : itemsQ.isFetching ? (
      <SkeletonTable rows={4} columns={4} />
    ) : (
      <EmptyState
        icon={<Factory size={28} />}
        title={t('plant.item.missing_title', { defaultValue: 'This item is not in the register' })}
        description={t('plant.item.missing_body', {
          defaultValue: 'It may belong to another project or the link is out of date.',
        })}
        action={{ label: t('plant.item.back', { defaultValue: 'Back to the register' }), onClick: () => go({ item: null }) }}
      />
    );
  } else if (items.length === 0 && tab !== 'site_it') {
    body = (
      <EmptyState
        icon={<Factory size={28} />}
        title={t('plant.page.empty_title', { defaultValue: 'No plant items yet' })}
        description={t('plant.page.empty_body', {
          defaultValue:
            'Start with the equipment that takes longest to get, such as the main transformer or the switchgear. Add it here, then record its lead time and the day it is needed.',
        })}
        action={!mayAdd ? undefined : { label: t('plant.item.add_submit', { defaultValue: 'Add item' }), onClick: () => setAdding(true) }}
      />
    );
  } else if (tab === 'long_lead') {
    body = (
      <LongLeadTimeline items={items} catalogue={catalogue} labels={labels} today={localToday()} onOpen={(id) => go({ item: id })} />
    );
  } else if (tab === 'limits') {
    body =
      pending(matrixQ, t('plant.limits.load_failed', { defaultValue: 'The delivery limits could not be loaded' })) ??
      (matrixQ.data ? (
        <DeliveryLimitsMatrix matrix={matrixQ.data} catalogue={catalogue} labels={labels} onOpen={(id) => go({ item: id })} />
      ) : null);
  } else if (tab === 'site_it') {
    body =
      pending(itQ, t('plant.it.load_failed', { defaultValue: 'The IT services could not be loaded' })) ??
      pending(frameQ, t('plant.site.load_failed', { defaultValue: 'The site plant could not be loaded' })) ?? (
        <SiteItPanel
          projectId={projectId}
          services={itQ.data ?? []}
          sitePlant={frameQ.data?.site_plant ?? []}
          catalogue={catalogue}
          labels={labels}
          onChanged={invalidate}
        />
      );
  } else if (tab === 'frame') {
    body =
      pending(frameQ, t('plant.frame.load_failed', { defaultValue: 'The frame summary could not be loaded' })) ??
      (frameQ.data ? (
        <FrameSummary
          projectId={projectId}
          summary={frameQ.data}
          readiness={readinessQ.data ?? null}
          findings={findingsQ.data ?? []}
          catalogue={catalogue}
          labels={labels}
        />
      ) : null);
  } else {
    body = <RegisterTable items={items} total={page.total} catalogue={catalogue} labels={labels} onOpen={(id) => go({ item: id })} />;
  }

  return (
    <PlantCanContext.Provider value={can}>
    <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="plant-register-page">
      {header}
      {readOnly && (
        <div role="status" data-testid="plant-read-only" className="rounded-md border border-border bg-surface-secondary p-3 text-sm">
          <p className="font-medium text-content-primary">
            {t('plant.page.read_only', { defaultValue: 'You can read the plant register but not change it.' })}
          </p>
          <p className="text-content-secondary">{readOnly}</p>
        </div>
      )}
      {!itemId && (
        <TabBar<Tab>
          ariaLabel={t('plant.page.tabs', { defaultValue: 'Plant register sections' })}
          activeId={tab}
          onChange={(id) => go({ tab: id === 'register' ? null : id })}
          idPrefix="plant-register"
          tabs={[
            { id: 'register', label: t('plant.tab.register', { defaultValue: 'Register' }), icon: <ListChecks size={14} /> },
            {
              id: 'long_lead',
              label: t('plant.tab.long_lead', { defaultValue: 'Long-lead timeline' }),
              icon: <CalendarClock size={14} />,
              badge: overdue > 0 ? overdue : undefined,
            },
            { id: 'limits', label: t('plant.tab.limits', { defaultValue: 'Delivery limits' }), icon: <Grid3x3 size={14} /> },
            { id: 'site_it', label: t('plant.tab.site_it', { defaultValue: 'Site and IT' }), icon: <Router size={14} /> },
            { id: 'frame', label: t('plant.tab.frame', { defaultValue: 'Frame summary' }), icon: <Factory size={14} /> },
          ]}
        />
      )}
      {body}
      {adding && (
        <ItemDialog
          open
          onClose={() => setAdding(false)}
          projectId={projectId}
          item={null}
          catalogue={catalogue}
          labels={labels}
          personName={personName}
          onSaved={(created) => {
            setAdding(false);
            void invalidate();
            go({ item: created.id, tab: null });
          }}
        />
      )}
    </div>
    </PlantCanContext.Provider>
  );
}
