/**
 * KvList / Kv — compact two-column key/value description list.
 *
 * Originally co-located in `features/bim/AssetDetailDrawer.tsx`; extracted
 * to `shared/ui/` so the cost database's variant detail panel and any
 * future drawer can reuse the same visual primitives.
 *
 * Styles preserved verbatim from the original definition.
 */
import type { ReactNode } from 'react';

export function KvList({ children }: { children: ReactNode }) {
  return <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1 text-[12px]">{children}</dl>;
}

export function Kv({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: ReactNode | string | null;
  mono?: boolean;
}) {
  const isEmptyVal = value == null || value === '';
  return (
    <>
      <dt className="text-[11px] text-content-tertiary">{label}</dt>
      <dd
        className={`min-w-0 break-words ${
          isEmptyVal ? 'text-content-quaternary' : 'text-content-primary'
        } ${mono ? 'font-mono text-[11px]' : ''}`}
      >
        {isEmptyVal ? '—' : value}
      </dd>
    </>
  );
}
