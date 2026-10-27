// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Accounting sync: connect the platform to the books. Xero and QuickBooks sync
 * live through OAuth; DATEV, the journal and SAF-T produce files for an
 * accountant. One screen: the list of connections on top, and for the selected
 * one the Sync, Mapping, Exports and Settings tabs.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { BookOpen, KeyRound, Plus, Trash2 } from 'lucide-react';
import { Button, Card, ConfirmDialog, EmptyState, TabBar, WideModal, tabIds } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { projectsApi } from '@/features/projects/api';
import {
  LIVE_PROVIDERS,
  PROVIDERS,
  createConnection,
  deleteConnection,
  needsAuthorisation,
  oauthRedirectUri,
  startOAuth,
  updateConnection,
  useConnections,
  useSyncMutation,
  useTemplates,
  type Connection,
  type DateRange,
  type Provider,
} from './api';
import { ConnectionForm, type ProjectOption } from './ConnectionForm';
import { ExportsTab } from './ExportsTab';
import { MappingTab } from './MappingTab';
import { SyncTab } from './SyncTab';
import { providerHelp, providerLabel } from './labels';
import { StatusChip } from './ui';

type TabId = 'sync' | 'mapping' | 'exports' | 'settings';

/** Pure: the tab a connection opens on. Live connections sync, file targets export. */
export function defaultTab(provider: Provider): TabId {
  return LIVE_PROVIDERS.includes(provider) ? 'sync' : 'exports';
}

function ProviderPicker({ onPick }: { onPick: (p: Provider) => void }) {
  const { t } = useTranslation();
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2" data-testid="accounting-sync-provider-picker">
      {PROVIDERS.map((p) => (
        <button
          key={p}
          type="button"
          onClick={() => onPick(p)}
          data-testid={`provider-${p}`}
          className="rounded-xl border border-border-light bg-surface-primary p-3 text-left transition-colors hover:border-oe-blue hover:bg-oe-blue-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
        >
          <span className="text-sm font-semibold text-content-primary">{providerLabel(t, p)}</span>
          <span className="mt-1 block text-xs leading-relaxed text-content-tertiary">{providerHelp(t, p)}</span>
        </button>
      ))}
    </div>
  );
}

function AddConnectionDialog({
  projects,
  onClose,
  onCreated,
}: {
  projects: ProjectOption[];
  onClose: () => void;
  onCreated: (c: Connection) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [provider, setProvider] = useState<Provider | null>(null);
  const catalogQ = useTemplates('');
  const createMut = useSyncMutation(createConnection);

  return (
    <WideModal
      open
      onClose={onClose}
      busy={createMut.isPending}
      size="lg"
      title={t('accountingSync.add.title', { defaultValue: 'Add connection' })}
      subtitle={
        provider
          ? providerHelp(t, provider)
          : t('accountingSync.add.subtitle', { defaultValue: 'Choose how the books are fed.' })
      }
    >
      {provider === null ? (
        <ProviderPicker onPick={setProvider} />
      ) : (
        <ConnectionForm
          provider={provider}
          existing={null}
          projects={projects}
          catalog={catalogQ.data}
          pending={createMut.isPending}
          readOnly={false}
          submitLabel={t('accountingSync.add.create', { defaultValue: 'Create connection' })}
          onCancel={() => setProvider(null)}
          onSubmit={(body) =>
            createMut.mutate(
              { ...body, provider },
              {
                onSuccess: (c) => {
                  addToast({ type: 'success', title: t('accountingSync.add.created', { defaultValue: 'Connection created' }) });
                  onCreated(c);
                },
                onError: (e) =>
                  addToast({
                    type: 'error',
                    title: t('accountingSync.add.failed', { defaultValue: 'Could not create the connection' }),
                    message: getErrorMessage(e),
                  }),
              },
            )
          }
        />
      )}
    </WideModal>
  );
}

function ConnectionCard({ c, selected, onSelect }: { c: Connection; selected: boolean; onSelect: () => void }) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      data-testid={`connection-${c.id}`}
      className={clsx(
        'min-w-[13rem] flex-1 rounded-xl border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
        selected ? 'border-oe-blue bg-oe-blue-subtle' : 'border-border-light bg-surface-primary hover:border-oe-blue/50',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-semibold text-content-primary">{c.name}</span>
        {c.last_sync_status && <StatusChip status={c.last_sync_status} />}
      </div>
      <div className="mt-0.5 text-xs text-content-secondary">
        {providerLabel(t, c.provider)}
        {c.is_sandbox && ` · ${t('accountingSync.card.sandbox', { defaultValue: 'sandbox' })}`}
      </div>
      <div className="mt-1 text-2xs text-content-tertiary">
        {needsAuthorisation(c) ? (
          <span className="text-amber-700 dark:text-amber-400">{t('accountingSync.card.not_authorised', { defaultValue: 'Not authorised yet' })}</span>
        ) : c.last_sync_at ? (
          <>
            {t('accountingSync.card.last_sync', { defaultValue: 'Last sync' })}: <DateDisplay value={c.last_sync_at} />
          </>
        ) : (
          t('accountingSync.card.never', { defaultValue: 'Never synced' })
        )}
      </div>
    </button>
  );
}

export function AccountingSyncPage() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const isAdmin = useAuthStore((s) => s.userRole) === 'admin';
  const { confirm, ...confirmProps } = useConfirm();
  const [params, setParams] = useSearchParams();
  const connectionsQ = useConnections();
  const projectsQ = useQuery({ queryKey: ['projects'], queryFn: projectsApi.list, staleTime: 5 * 60 * 1000 });
  const projects = useMemo<ProjectOption[]>(
    () => (projectsQ.data ?? []).map((p) => ({ id: p.id, name: p.name })),
    [projectsQ.data],
  );
  const [addOpen, setAddOpen] = useState(false);
  const [tab, setTab] = useState<TabId | null>(null);
  const [range, setRange] = useState<DateRange>({});

  const connections = connectionsQ.data ?? [];
  const selectedId = params.get('connection') ?? connections[0]?.id ?? '';
  const selected = connections.find((c) => c.id === selectedId) ?? null;
  const activeTab: TabId = tab ?? (selected ? defaultTab(selected.provider) : 'sync');

  const catalogQ = useTemplates(selected?.country_code ?? '');
  const updateMut = useSyncMutation((v: { id: string; body: Parameters<typeof updateConnection>[1] }) => updateConnection(v.id, v.body));
  const deleteMut = useSyncMutation((id: string) => deleteConnection(id));
  const authMut = useSyncMutation((id: string) => startOAuth(id, oauthRedirectUri()));

  useEffect(() => {
    setTab(null);
  }, [selectedId]);

  const select = (id: string) => setParams({ connection: id }, { replace: true });
  const onError = (err: unknown) =>
    addToast({ type: 'error', title: t('accountingSync.error', { defaultValue: 'Error' }), message: getErrorMessage(err) });

  const handleDelete = async (c: Connection) => {
    const ok = await confirm({
      title: t('accountingSync.delete.title', { defaultValue: 'Delete this connection?' }),
      message: t('accountingSync.delete.msg', {
        defaultValue: 'The mapping and the sync log of this connection are removed. Documents already in your books stay there.',
      }),
      confirmLabel: t('accountingSync.delete.confirm', { defaultValue: 'Delete' }),
      variant: 'danger',
    });
    if (ok) deleteMut.mutate(c.id, { onSuccess: () => setParams({}, { replace: true }), onError });
  };

  const tabs = [
    { id: 'sync' as const, label: t('accountingSync.tab.sync', { defaultValue: 'Sync' }) },
    { id: 'mapping' as const, label: t('accountingSync.tab.mapping', { defaultValue: 'Mapping' }) },
    { id: 'exports' as const, label: t('accountingSync.tab.exports', { defaultValue: 'Exports' }) },
    { id: 'settings' as const, label: t('accountingSync.tab.settings', { defaultValue: 'Settings' }) },
  ];

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('accountingSync.title', { defaultValue: 'Accounting sync' })}
        subtitle={t('accountingSync.subtitle', {
          defaultValue: 'Send invoices and bills to your accounting software, or hand your accountant a file.',
        })}
        actions={
          isAdmin ? (
            <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={() => setAddOpen(true)}>
              {t('accountingSync.add.title', { defaultValue: 'Add connection' })}
            </Button>
          ) : undefined
        }
      />

      {connectionsQ.isLoading ? (
        <Card padding="lg" className="text-center text-sm text-content-tertiary">{t('accountingSync.loading', { defaultValue: 'Loading...' })}</Card>
      ) : connections.length === 0 ? (
        <Card padding="md">
          <EmptyState
            icon={<BookOpen size={28} />}
            title={t('accountingSync.empty.title', { defaultValue: 'No accounting connection yet' })}
            description={t('accountingSync.empty.desc', {
              defaultValue: 'Connect Xero or QuickBooks for a live sync, or set up DATEV, a journal or SAF-T to export files.',
            })}
            action={
              isAdmin ? (
                <Button variant="primary" icon={<Plus size={14} />} onClick={() => setAddOpen(true)}>
                  {t('accountingSync.add.title', { defaultValue: 'Add connection' })}
                </Button>
              ) : undefined
            }
          />
          {!isAdmin && (
            <p className="mt-2 text-center text-xs text-content-tertiary">
              {t('accountingSync.admin_only', { defaultValue: 'Only an administrator can set up or change connections.' })}
            </p>
          )}
        </Card>
      ) : (
        <>
          <div className="flex flex-wrap gap-3" data-testid="accounting-sync-connections">
            {connections.map((c) => (
              <ConnectionCard key={c.id} c={c} selected={c.id === selected?.id} onSelect={() => select(c.id)} />
            ))}
          </div>

          {selected && (
            <div className="space-y-4">
              <TabBar
                tabs={tabs}
                activeId={activeTab}
                onChange={setTab}
                ariaLabel={t('accountingSync.tabs_label', { defaultValue: 'Accounting sync sections' })}
                idPrefix="accounting-sync"
              />
              <div role="tabpanel" id={tabIds('accounting-sync').panelId(activeTab)} aria-labelledby={tabIds('accounting-sync').tabId(activeTab)}>
                {activeTab === 'sync' && <SyncTab connection={selected} range={range} onRange={setRange} canEdit={isAdmin} />}
                {activeTab === 'mapping' && <MappingTab connectionId={selected.id} canEdit={isAdmin} />}
                {activeTab === 'exports' && <ExportsTab connection={selected} range={range} onRange={setRange} />}
                {activeTab === 'settings' && (
                  <Card padding="md" data-testid="accounting-sync-settings">
                    {!isAdmin && (
                      <p className="mb-3 text-xs text-content-tertiary">
                        {t('accountingSync.admin_only', { defaultValue: 'Only an administrator can set up or change connections.' })}
                      </p>
                    )}
                    <ConnectionForm
                      key={`${selected.id}-${selected.last_sync_at ?? ''}-${selected.is_authorised}`}
                      provider={selected.provider}
                      existing={selected}
                      projects={projects}
                      catalog={catalogQ.data}
                      pending={updateMut.isPending}
                      readOnly={!isAdmin}
                      submitLabel={t('accountingSync.settings.save', { defaultValue: 'Save settings' })}
                      onSubmit={(body) =>
                        updateMut.mutate(
                          { id: selected.id, body },
                          {
                            onSuccess: () => addToast({ type: 'success', title: t('accountingSync.settings.saved', { defaultValue: 'Settings saved' }) }),
                            onError,
                          },
                        )
                      }
                      extraActions={
                        isAdmin ? (
                          <>
                            {LIVE_PROVIDERS.includes(selected.provider) && (
                              <Button
                                type="button"
                                variant="secondary"
                                icon={<KeyRound size={14} />}
                                loading={authMut.isPending}
                                disabled={!selected.client_id || !selected.has_client_secret}
                                onClick={() =>
                                  authMut.mutate(selected.id, {
                                    onSuccess: (r) => window.location.assign(r.authorization_url),
                                    onError,
                                  })
                                }
                              >
                                {selected.is_authorised
                                  ? t('accountingSync.settings.reauthorise', { defaultValue: 'Authorise again' })
                                  : t('accountingSync.settings.authorise', { defaultValue: 'Authorise' })}
                              </Button>
                            )}
                            <Button type="button" variant="ghost" icon={<Trash2 size={14} />} onClick={() => handleDelete(selected)}>
                              {t('accountingSync.delete.confirm', { defaultValue: 'Delete' })}
                            </Button>
                          </>
                        ) : undefined
                      }
                    />
                    {LIVE_PROVIDERS.includes(selected.provider) && (!selected.client_id || !selected.has_client_secret) && (
                      <p className="mt-2 text-xs text-content-tertiary">
                        {t('accountingSync.settings.authorise_hint', { defaultValue: 'Save the client ID and secret first, then authorise.' })}
                      </p>
                    )}
                  </Card>
                )}
              </div>
            </div>
          )}
        </>
      )}

      {addOpen && (
        <AddConnectionDialog
          projects={projects}
          onClose={() => setAddOpen(false)}
          onCreated={(c) => {
            setAddOpen(false);
            select(c.id);
          }}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
