// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Dashboard widget - one row per client that has projects: how many, how
// many are active, and the contract value they add up to (per currency,
// never blended). Each row deep-links to the projects list filtered to
// that client; the footer opens the Contacts directory on clients.

import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight, BookUser, FolderOpen, Palette, Pencil, Users } from 'lucide-react';

import { Card, EmptyState } from '@/shared/ui';
import { fmtFixed, fmtNumber } from '@/shared/lib/formatters';
import { projectsApi, type Project } from '@/features/projects/api';
import {
  clientLabel,
  findClient,
  formatAddress,
  isUuid,
  primaryAddress,
  useClientLookup,
} from '@/features/projects/clients';
import {
  ClientColorSwatch,
  ColorDisc,
  type ClientColorSwatchHandle,
} from '@/features/projects/ClientColorSwatch';
import { ClientMenu, useClientMenu, type ClientMenuItem } from '@/features/projects/ClientMenu';
import { ClientEditorDialog } from '@/features/projects/ClientEditorDialog';
import type { Contact } from '@/features/contacts/api';

interface ClientRow {
  key: string;
  label: string;
  projects: number;
  active: number;
  /** currency -> summed contract_value; only projects that carry one. */
  value: Map<string, number>;
}

/** Compact money: 1.2M / 850K / 940, with the ISO code alongside. The
 *  thresholds sit where the rounded figure rolls over, so 999,600 prints
 *  "1.0M" rather than "1,000K". */
export function compactMoney(v: number, currency: string): string {
  const figure =
    v >= 999_500
      ? `${fmtFixed(v / 1_000_000, 1)}M`
      : v >= 999.5
        ? `${fmtFixed(v / 1_000, 0)}K`
        : fmtNumber(v, 0);
  return currency ? `${figure} ${currency}` : figure;
}

export function buildClientRows(
  projects: readonly Project[],
  labelOf: (clientId: string) => string,
): ClientRow[] {
  const rows = new Map<string, ClientRow>();
  for (const p of projects) {
    const key = (p.client_id ?? '').trim();
    if (!key) continue;
    let row = rows.get(key);
    if (!row) {
      row = { key, label: labelOf(key), projects: 0, active: 0, value: new Map() };
      rows.set(key, row);
    }
    row.projects += 1;
    if (p.status === 'active') row.active += 1;
    const amount = Number(p.contract_value);
    if (p.contract_value != null && p.contract_value !== '' && Number.isFinite(amount) && amount > 0) {
      const cur = p.currency || '';
      row.value.set(cur, (row.value.get(cur) ?? 0) + amount);
    }
  }
  return Array.from(rows.values()).sort(
    (a, b) => b.projects - a.projects || a.label.localeCompare(b.label),
  );
}

export function ClientsCard() {
  const { t } = useTranslation();
  // Same key + endpoint as the dashboard's own projects query, so this
  // widget rides the cache instead of adding a fetch. The default list
  // excludes archived projects, which is the portfolio a client "has".
  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
    staleTime: 5 * 60_000,
  });
  const { lookup, isLoading: directoryLoading } = useClientLookup();

  const unknown = t('projects.client_unknown', { defaultValue: 'Unknown client' });
  const rows = useMemo(
    () => buildClientRows(projects ?? [], (id) => clientLabel(id, lookup, unknown)),
    [projects, lookup, unknown],
  );

  const loading = projectsLoading || (rows.length > 0 && directoryLoading);

  // Right-click on a row: edit / colour / open projects / manage in contacts.
  const navigate = useNavigate();
  const menu = useClientMenu();
  const [menuRow, setMenuRow] = useState<{ key: string; label: string; contact?: Contact } | null>(null);
  const [editing, setEditing] = useState<Contact | null>(null);
  const swatchRefs = useRef(new Map<string, ClientColorSwatchHandle>());
  const menuItems: ClientMenuItem[] = menuRow
    ? [
        {
          key: 'edit',
          label: t('projects.client_menu.edit', { defaultValue: 'Edit client...' }),
          icon: <Pencil size={13} />,
          disabled: !menuRow.contact,
          onSelect: () => setEditing(menuRow.contact ?? null),
        },
        {
          key: 'colour',
          label: t('projects.client_menu.set_colour', { defaultValue: 'Set colour...' }),
          icon: <Palette size={13} />,
          disabled: !menuRow.contact,
          onSelect: () => swatchRefs.current.get(menuRow.key)?.open(),
        },
        {
          key: 'projects',
          label: t('projects.client_menu.open_projects', { defaultValue: 'Open projects' }),
          icon: <FolderOpen size={13} />,
          separatorBefore: true,
          onSelect: () => navigate(`/projects?client=${encodeURIComponent(menuRow.key)}`),
        },
        {
          key: 'contacts',
          label: t('projects.client_menu.manage_contacts', { defaultValue: 'Manage in contacts' }),
          icon: <BookUser size={13} />,
          onSelect: () =>
            navigate(
              menuRow.contact
                ? `/contacts?contactId=${encodeURIComponent(menuRow.key)}`
                : '/contacts?contact_type=client',
            ),
        },
      ]
    : [];

  return (
    <Card padding="md" data-testid="clients-card" className="flex h-full flex-col">
      <ClientMenu anchor={menu.anchor} items={menuItems} onClose={menu.close} title={menuRow?.label} />
      <ClientEditorDialog contact={editing} onClose={() => setEditing(null)} />
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('dashboard.clients.title', { defaultValue: 'Clients' })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('dashboard.clients.subtitle', {
              defaultValue: 'Who the work is for, and how much of it each has with you.',
            })}
          </p>
        </div>
        <Users size={18} className="text-content-tertiary" />
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-9 w-full animate-pulse rounded-md bg-surface-secondary" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<Users size={32} strokeWidth={1.5} />}
          title={t('dashboard.clients.empty_title', { defaultValue: 'No clients yet' })}
          description={t('dashboard.clients.empty_description', {
            defaultValue:
              'No projects have a client yet - set one when you create or edit a project.',
          })}
        />
      ) : (
        <ul className="divide-y divide-border-light" data-testid="clients-card-rows">
          {rows.map((row) => {
            const values = Array.from(row.value.entries()).sort((a, b) => b[1] - a[1]);
            // The swatch is a button, so it sits BESIDE the row link rather
            // than inside it - a legacy free-text client has no contact to
            // hold a colour and gets an inert grey ring.
            const contact = findClient(row.key, lookup);
            const address = formatAddress(primaryAddress(contact));
            return (
              <li
                key={row.key}
                className="flex items-center gap-2"
                data-testid="clients-card-row"
                onContextMenu={(e) => {
                  setMenuRow({ key: row.key, label: row.label, contact });
                  menu.openAt(e);
                }}
              >
                {contact ? (
                  <ClientColorSwatch
                    ref={(h) => {
                      if (h) swatchRefs.current.set(row.key, h);
                      else swatchRefs.current.delete(row.key);
                    }}
                    contact={contact}
                    clientName={row.label}
                    size="sm"
                  />
                ) : (
                  <span
                    className="inline-flex p-0.5"
                    title={
                      isUuid(row.key)
                        ? unknown
                        : t('projects.client_picker.legacy', { defaultValue: 'not linked' })
                    }
                  >
                    <ColorDisc hex="" size={16} />
                  </span>
                )}
                <Link
                  to={`/projects?client=${encodeURIComponent(row.key)}`}
                  className="group flex min-w-0 flex-1 items-center justify-between gap-3 py-2 text-sm transition-colors hover:text-oe-blue"
                  title={t('dashboard.clients.open_projects', {
                    defaultValue: 'Show projects for {{name}}',
                    name: row.label,
                  })}
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium text-content-primary group-hover:text-oe-blue">
                      {row.label}
                    </div>
                    {address && (
                      <div
                        className="truncate text-[11px] text-content-tertiary"
                        title={address}
                        data-testid="clients-card-address"
                      >
                        {address}
                      </div>
                    )}
                    <div className="text-xs text-content-tertiary tabular-nums">
                      {t('dashboard.clients.project_count', {
                        defaultValue_one: '{{count}} project',
                        defaultValue_other: '{{count}} projects',
                        defaultValue: '{{count}} projects',
                        count: row.projects,
                      })}
                      {' · '}
                      {t('dashboard.clients.active_count', {
                        defaultValue: '{{count}} active',
                        count: row.active,
                      })}
                    </div>
                  </div>
                  <div className="shrink-0 text-end text-xs tabular-nums text-content-secondary">
                    {values.length === 0 ? (
                      <span className="text-content-quaternary">—</span>
                    ) : (
                      values.map(([cur, total]) => (
                        <div key={cur || 'unknown'}>{compactMoney(total, cur)}</div>
                      ))
                    )}
                  </div>
                  <ArrowRight
                    size={14}
                    className="shrink-0 text-content-tertiary transition-transform group-hover:translate-x-0.5 group-hover:text-oe-blue"
                  />
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      <div className="mt-auto border-t border-border-light pt-2">
        <Link
          to="/contacts?contact_type=client"
          className="inline-flex items-center gap-1 text-xs font-medium text-oe-blue hover:underline"
        >
          {t('dashboard.clients.manage', { defaultValue: 'Manage clients' })}
          <ArrowRight size={12} />
        </Link>
      </div>
    </Card>
  );
}
