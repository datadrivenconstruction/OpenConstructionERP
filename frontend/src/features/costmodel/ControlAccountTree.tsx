// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ControlAccountTree - left-hand tree of control accounts. Selecting an
// account filters the spine grid to that account (and, by convention in the
// panel, its descendants). An "All accounts" pseudo-row clears the filter.

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { FolderTree } from 'lucide-react';

import type { ControlAccount } from './api';

export interface ControlAccountTreeProps {
  /** Tree-ordered control accounts (parent before children) from the rollup. */
  accounts: ControlAccount[];
  /** Currently selected account id, or null for "all accounts". */
  selectedId: string | null;
  /** Invoked with the account id (or null to clear the filter). */
  onSelect: (id: string | null) => void;
  /** Optional per-account cost-line counts to show as a badge. */
  counts?: Record<string, number>;
}

/** Depth of an account in the tree, derived by walking parent_id links. */
function computeDepth(account: ControlAccount, byId: Map<string, ControlAccount>): number {
  let depth = 0;
  let current: ControlAccount | undefined = account;
  // Guard against cycles with a hard cap.
  const seen = new Set<string>();
  while (current?.parent_id && !seen.has(current.id)) {
    seen.add(current.id);
    current = byId.get(current.parent_id);
    if (!current) break;
    depth += 1;
    if (depth > 32) break;
  }
  return depth;
}

/**
 * Vertical list/tree of control accounts. Pure presentational: the parent
 * owns the selection state and feeds it back via ``onSelect``.
 */
export function ControlAccountTree({
  accounts,
  selectedId,
  onSelect,
  counts,
}: ControlAccountTreeProps) {
  const { t } = useTranslation();

  const byId = useMemo(() => {
    const map = new Map<string, ControlAccount>();
    for (const a of accounts) map.set(a.id, a);
    return map;
  }, [accounts]);

  const rows = useMemo(
    () => accounts.map((a) => ({ account: a, depth: computeDepth(a, byId) })),
    [accounts, byId],
  );

  return (
    <nav
      aria-label={t('costmodel.spine.accounts_tree', { defaultValue: 'Control accounts' })}
      className="space-y-0.5"
    >
      <button
        type="button"
        onClick={() => onSelect(null)}
        aria-current={selectedId === null ? 'true' : undefined}
        className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
          selectedId === null
            ? 'bg-oe-blue-subtle/60 font-medium text-oe-blue-text'
            : 'text-content-secondary hover:bg-surface-secondary'
        }`}
      >
        <FolderTree size={14} className="shrink-0" />
        <span className="truncate">
          {t('costmodel.spine.all_accounts', { defaultValue: 'All accounts' })}
        </span>
      </button>

      {rows.map(({ account, depth }) => {
        const isSelected = account.id === selectedId;
        const count = counts?.[account.id];
        return (
          <button
            key={account.id}
            type="button"
            onClick={() => onSelect(account.id)}
            aria-current={isSelected ? 'true' : undefined}
            title={`${account.code} ${account.title || account.name}`}
            className={`flex w-full items-center gap-2 rounded-md py-1.5 pr-2 text-left text-sm transition-colors ${
              isSelected
                ? 'bg-oe-blue-subtle/60 font-medium text-oe-blue-text'
                : 'text-content-secondary hover:bg-surface-secondary'
            }`}
            style={{ paddingLeft: `${8 + depth * 14}px` }}
          >
            <span className="shrink-0 font-mono text-2xs text-content-tertiary">
              {account.code}
            </span>
            <span className="min-w-0 flex-1 truncate">{account.title || account.name}</span>
            {typeof count === 'number' && (
              <span className="shrink-0 rounded-full bg-surface-secondary px-1.5 text-2xs font-medium text-content-secondary">
                {count}
              </span>
            )}
          </button>
        );
      })}

      {accounts.length === 0 && (
        <p className="px-2 py-3 text-xs text-content-tertiary">
          {t('costmodel.spine.no_accounts', { defaultValue: 'No control accounts yet.' })}
        </p>
      )}
    </nav>
  );
}
