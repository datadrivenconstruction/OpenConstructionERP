import { useId, type ReactNode } from 'react';

/**
 * Keeps a block of controls on screen but disabled, with one sentence saying
 * who can use it. Wraps native controls in a disabled fieldset, so every
 * button, input and select inside is unavailable without per-control wiring.
 * The reason is printed in the block, not only in a tooltip, so it reads on a
 * touch screen and a narrow phone, and the fieldset points at it with
 * `aria-describedby`. With no `reason` the block is fully active and renders
 * no extra box.
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
  const hintId = useId();
  return (
    <fieldset
      disabled={!!why}
      title={why}
      aria-describedby={why ? hintId : undefined}
      className={`m-0 min-w-0 border-0 p-0 ${className ?? 'contents'}`}
    >
      {why && (
        <span id={hintId} role="note" className="block w-full basis-full text-2xs leading-snug text-content-tertiary">
          {why}
        </span>
      )}
      {children}
    </fieldset>
  );
}
