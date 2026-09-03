// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * askDialog — a promise-based prompt / confirm replacement.
 *
 * Some deployments run in a browser that refuses `prompt()` and
 * `confirm()` outright, so a flow that called `window.prompt` silently
 * did nothing. One promise-based dialog does every ask instead - a
 * value, a reason, a confirmation - with Enter to accept, Escape to
 * cancel, and the first field focused and selected on open.
 *
 *     const [code] = (await ask({
 *       title: 'Job Number',
 *       fields: [{ label: 'Job number', placeholder: 'e.g. 25406' }],
 *     })) ?? [];
 *     if (!code) return;             // cancelled
 *
 * Self-contained on purpose: React plus a one-time injected style block,
 * no module-specific stylesheet, so any feature can depend on it without
 * pulling in another module.
 */

import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';

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

const STYLE_ID = 'oe-ask-dialog-styles';

/** Inject the dialog's styles once. Theme-aware via the app's own
 *  `.dark` class, with self-contained fallbacks so it never borrows a
 *  half-defined palette. */
function ensureStyles(): void {
  if (document.getElementById(STYLE_ID)) return;
  const el = document.createElement('style');
  el.id = STYLE_ID;
  el.textContent = `
.oe-ask-scrim{position:fixed;inset:0;z-index:1200;display:flex;align-items:center;
  justify-content:center;background:rgba(15,23,42,.5);backdrop-filter:blur(2px);padding:16px;}
.oe-ask-card{width:min(460px,94vw);background:#fff;color:#1f2937;border:1px solid #e2e8f0;
  border-radius:12px;padding:20px 22px;box-shadow:0 20px 50px rgba(15,23,42,.35);
  font:14px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif;}
.oe-ask-title{font-size:15px;font-weight:700;margin-bottom:4px;}
.oe-ask-note{font-size:12.5px;color:#64748b;margin-bottom:12px;}
.oe-ask-field{margin-bottom:10px;}
.oe-ask-label{font-size:12px;font-weight:600;color:#475569;margin-bottom:3px;}
.oe-ask-card input,.oe-ask-card textarea{width:100%;font:inherit;font-size:13px;
  border:1px solid #cbd5e1;border-radius:8px;padding:8px 10px;background:#fff;color:#1f2937;
  box-sizing:border-box;}
.oe-ask-card textarea{min-height:70px;resize:vertical;}
.oe-ask-card input:focus,.oe-ask-card textarea:focus{outline:2px solid #93c5fd;
  outline-offset:-1px;border-color:#3b82f6;}
.oe-ask-row{display:flex;gap:8px;justify-content:flex-end;margin-top:14px;}
.oe-ask-btn{font:inherit;font-size:13px;font-weight:600;border-radius:8px;padding:8px 16px;
  cursor:pointer;border:1px solid #cbd5e1;background:#fff;color:#334155;}
.oe-ask-btn.pri{background:#2563eb;border-color:#2563eb;color:#fff;}
.oe-ask-btn.dngr{background:#dc2626;border-color:#dc2626;color:#fff;}
.dark .oe-ask-card{background:#151c25;color:#e7edf4;border-color:#29333f;}
.dark .oe-ask-note{color:#8492a1;}
.dark .oe-ask-label{color:#b2becb;}
.dark .oe-ask-card input,.dark .oe-ask-card textarea{background:#1b232e;color:#e7edf4;border-color:#29333f;}
.dark .oe-ask-btn{background:#1b232e;color:#b2becb;border-color:#29333f;}
`;
  document.head.appendChild(el);
}

function AskDialog({ opts, resolve }: { opts: AskOptions; resolve: (v: string[] | null) => void }) {
  const fields = opts.fields ?? [];
  const [values, setValues] = useState<string[]>(fields.map((f) => f.value ?? ''));
  const firstRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);

  // Focus and select the first field once, when the dialog opens. This must
  // NOT depend on `values`: if it re-ran on every keystroke it would
  // re-select the field 30ms after each letter, so the next character typed
  // would overwrite the selection (the "types over the previous letter" bug).
  useEffect(() => {
    const t = setTimeout(() => {
      firstRef.current?.focus();
      firstRef.current?.select?.();
    }, 30);
    return () => clearTimeout(t);
  }, []);

  // Escape cancels; Enter (outside a textarea) accepts. This one needs the
  // live `values`, so it re-subscribes as they change — harmless, because it
  // only swaps a keydown listener and never touches focus or selection.
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
    <div className="oe-ask-scrim" onClick={() => resolve(null)}>
      <div className="oe-ask-card" onClick={(e) => e.stopPropagation()}>
        <div className="oe-ask-title">{opts.title}</div>
        {opts.note && <div className="oe-ask-note">{opts.note}</div>}

        {fields.map((f, i) => (
          <div key={f.label} className="oe-ask-field">
            <div className="oe-ask-label">{f.label}</div>
            {f.multiline ? (
              <textarea
                ref={i === 0 ? (firstRef as React.RefObject<HTMLTextAreaElement>) : undefined}
                placeholder={f.placeholder}
                value={values[i] ?? ''}
                onChange={(e) => setValues((v) => v.map((x, j) => (j === i ? e.target.value : x)))}
              />
            ) : (
              <>
                <input
                  ref={i === 0 ? (firstRef as React.RefObject<HTMLInputElement>) : undefined}
                  placeholder={f.placeholder}
                  list={f.options?.length ? `oe-ask-opt-${i}` : undefined}
                  value={values[i] ?? ''}
                  onChange={(e) => setValues((v) => v.map((x, j) => (j === i ? e.target.value : x)))}
                />
                {f.options?.length ? (
                  <datalist id={`oe-ask-opt-${i}`}>
                    {f.options.map((o) => (
                      <option key={o} value={o} />
                    ))}
                  </datalist>
                ) : null}
              </>
            )}
          </div>
        ))}

        <div className="oe-ask-row">
          <button type="button" className="oe-ask-btn" onClick={() => resolve(null)}>
            {opts.cancelLabel ?? 'Cancel'}
          </button>
          <button
            type="button"
            className={`oe-ask-btn ${opts.danger ? 'dngr' : 'pri'}`}
            onClick={() => resolve(values)}
          >
            {opts.okLabel ?? 'OK'}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Ask for values. Resolves to the answers, or null if cancelled. */
export function ask(opts: AskOptions): Promise<string[] | null> {
  ensureStyles();
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

/** Yes/no, same contract. */
export async function askConfirm(title: string, note?: string, okLabel = 'Yes'): Promise<boolean> {
  const r = await ask({ title, note, fields: [], okLabel });
  return r !== null;
}
