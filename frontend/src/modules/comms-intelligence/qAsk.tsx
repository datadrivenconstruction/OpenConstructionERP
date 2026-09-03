// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * qAsk — the universal prompt replacement.
 *
 * This user's browser refuses `prompt()` and `confirm()` outright, so a
 * gate override that called `window.prompt` silently did nothing: the
 * refusal message never appeared and the award looked broken. One
 * promise-based dialog does every ask instead — a reason, a value, a
 * confirmation — with Enter to accept, Escape to cancel, and the first
 * field focused and selected on open.
 *
 *     const [reason] = (await qAsk({
 *       title: 'Pass the gate anyway?',
 *       note: 'It goes on the record.',
 *       fields: [{ label: 'Reason', placeholder: 'why…' }],
 *     })) ?? [];
 *     if (!reason) return;            // cancelled
 */

import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './ci.css';

export interface AskField {
  label: string;
  value?: string;
  placeholder?: string;
  /** Datalist options offered under the input. */
  options?: string[];
  multiline?: boolean;
}

export interface AskOptions {
  title: string;
  note?: string;
  fields?: AskField[];
  okLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}

function AskDialog({ opts, resolve }: { opts: AskOptions; resolve: (v: string[] | null) => void }) {
  const fields = opts.fields ?? [];
  const [values, setValues] = useState<string[]>(fields.map((f) => f.value ?? ''));
  const firstRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);

  // Focus and select the first field, one tick after mount so the browser
  // has laid the dialog out. This MUST run only once: with `values` in the
  // deps it re-ran on every keystroke, re-selecting the field 30ms after
  // each letter so the next character overwrote the selection (the "types
  // over the previous letter" bug).
  useEffect(() => {
    const t = setTimeout(() => {
      firstRef.current?.focus();
      firstRef.current?.select?.();
    }, 30);
    return () => clearTimeout(t);
  }, []);

  // Escape cancels; Enter (outside a textarea) accepts. This needs the live
  // `values`, so it re-subscribes as they change — harmless, because it only
  // swaps a keydown listener and never touches focus or selection.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        resolve(null);
      }
      if (e.key === 'Enter' && !e.shiftKey && !(e.target as HTMLElement)?.matches('textarea')) {
        e.preventDefault();
        resolve(values);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [resolve, values]);

  return (
    <div className="ci" style={{ position: 'fixed', inset: 0, zIndex: 82 }}>
      <div className="ci-scrim" onClick={() => resolve(null)}>
        <div
          onClick={(e) => e.stopPropagation()}
          style={{
            width: 'min(460px, 94vw)',
            background: 'var(--panel)',
            border: '1px solid var(--edge2)',
            borderRadius: 12,
            padding: '20px 22px',
            boxShadow: 'var(--sh)',
          }}
        >
          <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--navy)', marginBottom: 4 }}>{opts.title}</div>
          {opts.note && <div className="v" style={{ marginBottom: 12 }}>{opts.note}</div>}

          {fields.map((f, i) => (
            <div key={f.label} style={{ marginBottom: 10 }}>
              <div className="qlab" style={{ marginBottom: 3 }}>{f.label}</div>
              {f.multiline ? (
                <textarea
                  ref={i === 0 ? (firstRef as React.RefObject<HTMLTextAreaElement>) : undefined}
                  style={{ width: '100%', minHeight: 70 }}
                  placeholder={f.placeholder}
                  value={values[i] ?? ''}
                  onChange={(e) => setValues((v) => v.map((x, j) => (j === i ? e.target.value : x)))}
                />
              ) : (
                <>
                  <input
                    ref={i === 0 ? (firstRef as React.RefObject<HTMLInputElement>) : undefined}
                    style={{ width: '100%' }}
                    placeholder={f.placeholder}
                    list={f.options?.length ? `qask-opt-${i}` : undefined}
                    value={values[i] ?? ''}
                    onChange={(e) => setValues((v) => v.map((x, j) => (j === i ? e.target.value : x)))}
                  />
                  {f.options?.length ? (
                    <datalist id={`qask-opt-${i}`}>
                      {f.options.map((o) => (
                        <option key={o} value={o} />
                      ))}
                    </datalist>
                  ) : null}
                </>
              )}
            </div>
          ))}

          <div className="row" style={{ justifyContent: 'flex-end', marginTop: 14 }}>
            <button type="button" className="b" onClick={() => resolve(null)}>
              {opts.cancelLabel ?? 'Cancel'}
            </button>
            <button
              type="button"
              className={`b ${opts.danger ? 'dngr' : 'pri'}`}
              onClick={() => resolve(values)}
            >
              {opts.okLabel ?? 'OK'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Ask for values. Resolves to the answers, or null if cancelled. */
export function qAsk(opts: AskOptions): Promise<string[] | null> {
  return new Promise((resolve) => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    const done = (v: string[] | null) => {
      root.unmount();
      host.remove();
      resolve(v);
    };
    root.render(<AskDialog opts={opts} resolve={done} />);
  });
}

/** Yes/no, same contract. `danger` paints the accept button red - use it
 *  for anything that destroys a record rather than changing one. */
export async function qConfirm(
  title: string,
  note?: string,
  okLabel = 'Yes',
  danger = false,
): Promise<boolean> {
  const r = await qAsk({ title, note, fields: [], okLabel, danger });
  return r !== null;
}
