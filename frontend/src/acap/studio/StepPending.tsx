interface StepPendingProps {
  title: string;
}

export function StepPending({ title }: StepPendingProps) {
  return (
    <div className="rounded-md border border-border bg-surface-secondary p-4">
      <div className="text-sm font-semibold text-content-primary">{title}</div>
      <p className="mt-1 text-sm text-content-secondary">
        Segera di langkah berikutnya alur ini.
      </p>
    </div>
  );
}

export default StepPending;