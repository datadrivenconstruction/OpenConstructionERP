import type { ReactNode } from 'react';

/**
 * Keeps a block of controls on screen but disabled, with one sentence saying
 * who can use it. Wraps native controls in a disabled fieldset, so every
 * button, input and select inside is unavailable without per-control wiring.
 * With no `reason` the block is fully active and renders no extra box.
 */
export function DisabledGroup({
  reason,
  className,
  children,
}: {
  reason?: string | null;
  className?: string;
  children: ReactNode;
}) {
  const why = reason?.trim() || undefined;
  return (
    <fieldset
      disabled={!!why}
      title={why}
      className={`m-0 min-w-0 border-0 p-0 ${className ?? 'contents'}`}
    >
      {children}
    </fieldset>
  );
}
