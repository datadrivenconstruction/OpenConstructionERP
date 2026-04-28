/**
 * QtyTile — small framed numeric tile with label, value, and unit.
 *
 * Originally co-located in `features/bim/AssetDetailDrawer.tsx`; extracted
 * to `shared/ui/` so the cost database's variant detail panel can reuse
 * the same visual primitive.  Styles preserved verbatim.
 */

export function QtyTile({
  label,
  value,
  unit,
}: {
  label: string;
  value: number;
  unit: string;
}) {
  return (
    <div className="rounded border border-border-light bg-surface-secondary/50 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-content-tertiary">{label}</div>
      <div className="font-mono text-sm font-semibold text-content-primary">
        {value.toLocaleString(undefined, { maximumFractionDigits: 3 })}
        <span className="ml-1 text-[10px] font-normal text-content-secondary">{unit}</span>
      </div>
    </div>
  );
}
