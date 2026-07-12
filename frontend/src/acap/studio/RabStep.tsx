import { useCallback, useState } from 'react';
import { Loader2, AlertTriangle, Info } from 'lucide-react';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { generateRab, downloadRabCsv } from './rabApi';
import { buildRabCsv } from './rabCsv';
import type { RabResponse } from './rabApi';

type RabState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; data: RabResponse }
  | { status: 'no-layout' }
  | { status: 'error'; message: string };

function formatCurrency(value: string | number | null): string {
  if (value === null || value === undefined) return '—';
  const n = typeof value === 'string' ? parseFloat(value) : value;
  if (isNaN(n)) return String(value);
  return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', minimumFractionDigits: 0 }).format(n);
}

interface RabStepProps {
  projectId: string;
}

export function RabStep({ projectId }: RabStepProps) {
  const [state, setState] = useState<RabState>({ status: 'idle' });

  const handleGenerate = useCallback(async () => {
    setState({ status: 'loading' });
    try {
      const data = await generateRab(projectId);
      setState({ status: 'ready', data });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setState({ status: 'no-layout' });
      } else {
        setState({ status: 'error', message: getErrorMessage(err) });
      }
    }
  }, [projectId]);

  const handleExportCsv = useCallback(() => {
    if (state.status !== 'ready') return;
    downloadRabCsv(projectId, buildRabCsv(state.data.lines));
  }, [projectId, state]);

  if (state.status === 'no-layout') {
    return (
      <div className="rounded-md border border-border bg-surface-secondary p-4 text-sm text-content-secondary">
        Selesaikan langkah Konfirmasi dulu.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <button
        type="button"
        onClick={handleGenerate}
        disabled={state.status === 'loading'}
        className="inline-flex items-center gap-2 self-start rounded-md bg-oe-blue px-4 py-2 text-sm font-medium text-white hover:bg-oe-blue-hover disabled:opacity-50"
      >
        {state.status === 'loading' && <Loader2 size={16} className="animate-spin" />}
        Hitung RAB
      </button>

      {state.status === 'error' && (
        <div className="text-sm text-semantic-error">{state.message}</div>
      )}

      {state.status === 'ready' && (
        <>
          <div className="text-2xl font-semibold text-content-primary">
            {formatCurrency(state.data.grand_total)}
          </div>

          {state.data.price_missing_lines.length > 0 && (
            <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              <div className="flex items-start gap-2">
                <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                <div>
                  <p className="font-medium">
                    {state.data.price_missing_lines.length} item belum ada harga Batam — tidak dihitung di total
                  </p>
                </div>
              </div>
            </div>
          )}

          {state.data.not_covered.length > 0 && (
            <div className="rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">
              <div className="flex items-start gap-2">
                <Info size={16} className="mt-0.5 shrink-0" />
                <div>
                  <p className="font-medium">Belum dicakup engine:</p>
                  <ul className="mt-1 list-disc pl-5">
                    {state.data.not_covered.map((item, i) => (
                      <li key={i}>{item}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border bg-surface-secondary text-content-secondary">
                  <th className="p-2">Kode</th>
                  <th className="p-2">Uraian</th>
                  <th className="p-2">Unit</th>
                  <th className="p-2 text-right">Qty</th>
                  <th className="p-2 text-right">Harga Satuan</th>
                  <th className="p-2 text-right">Total</th>
                </tr>
              </thead>
              <tbody>
                {state.data.lines.map((line, i) => (
                  <tr key={i} className="border-b border-border-light">
                    <td className="p-2 text-content-secondary">{line.kode}</td>
                    <td className="p-2">
                      {line.uraian}
                      {line.price_missing && (
                        <span className="ml-2 inline-block rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                          HARGA BELUM ADA
                        </span>
                      )}
                    </td>
                    <td className="p-2">{line.unit}</td>
                    <td className="p-2 text-right">{line.quantity}</td>
                    <td className="p-2 text-right">{formatCurrency(line.unit_rate)}</td>
                    <td className="p-2 text-right">{formatCurrency(line.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <button
            type="button"
            onClick={handleExportCsv}
            className="self-start rounded-md border border-border px-3 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary"
          >
            Export CSV
          </button>
        </>
      )}
    </div>
  );
}

export default RabStep;
