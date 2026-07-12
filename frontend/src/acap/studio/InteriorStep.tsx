import { useCallback, useEffect, useState } from 'react';
import { Loader2, ImageOff } from 'lucide-react';
import { getLatestLayout } from '@/acap/floorPlanApi';
import { getErrorMessage, ApiError } from '@/shared/lib/api';
import { generateInterior, listInteriors, isNotConfiguredError, type InteriorRenderResponse } from './interiorApi';

const STYLES = [
  { id: 'minimalis', label: 'Minimalis', desc: 'Bersih, netral, fungsional' },
  { id: 'skandinavia', label: 'Skandinavia', desc: 'Terang, hangat, nyaman' },
  { id: 'japandi', label: 'Japandi', desc: 'Kayu hangat, zen, minimal' },
  { id: 'industrial', label: 'Industrial', desc: 'Beton ekspos, loft urban' },
  { id: 'klasik', label: 'Klasik', desc: 'Elegan, mewah, detail'} ,
];

interface RoomOption {
  level: number;
  name: string;
}

interface InteriorStepProps {
  projectId: string;
}

type GenerateState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'not-configured' }
  | { status: 'no-layout' }
  | { status: 'error'; message: string };

const STATUS_LABEL: Record<string, string> = {
  completed: 'Selesai',
  failed: 'Gagal',
  pending: 'Diproses',
};

export function InteriorStep({ projectId }: InteriorStepProps) {
  const [rooms, setRooms] = useState<RoomOption[]>([]);
  const [selectedRoom, setSelectedRoom] = useState('');
  const [selectedStyle, setSelectedStyle] = useState('japandi');
  const [interiors, setInteriors] = useState<InteriorRenderResponse[]>([]);
  const [generateState, setGenerateState] = useState<GenerateState>({ status: 'idle' });
  const [listError, setListError] = useState('');

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;

    getLatestLayout(projectId)
      .then((res) => {
        if (cancelled) return;
        const allRooms: RoomOption[] = [];
        for (const level of res.plan.levels) {
          for (const room of level.rooms) {
            allRooms.push({ level: level.level, name: room.name });
          }
        }
        setRooms(allRooms);
        if (allRooms.length > 0) setSelectedRoom(allRooms[0].name);
      })
      .catch(() => {});

    listInteriors(projectId)
      .then((items) => {
        if (!cancelled) setInteriors(items);
      })
      .catch((err) => {
        if (!cancelled) setListError(getErrorMessage(err));
      });

    return () => { cancelled = true; };
  }, [projectId]);

  const handleGenerate = useCallback(() => {
    if (!projectId || !selectedRoom) return;
    setGenerateState({ status: 'loading' });
    generateInterior(projectId, { room_name: selectedRoom, style: selectedStyle })
      .then((render) => {
        setGenerateState({ status: 'idle' });
        setInteriors((prev) => [render, ...prev]);
      })
      .catch((err) => {
        if (isNotConfiguredError(err)) {
          setGenerateState({ status: 'not-configured' });
        } else if (err instanceof ApiError && err.status === 404) {
          setGenerateState({ status: 'no-layout' });
        } else {
          setGenerateState({ status: 'error', message: getErrorMessage(err) });
        }
      });
  }, [projectId, selectedRoom, selectedStyle]);

  const isPending = generateState.status === 'loading';

  if (!projectId) return null;

  if (listError) {
    return <div className="p-6 text-sm text-semantic-error">{listError}</div>;
  }

  if (rooms.length === 0) {
    return (
      <div className="rounded-md border border-border bg-surface-secondary p-4 text-sm text-content-secondary">
        Selesaikan langkah Konfirmasi dulu, lalu simpan denah untuk mengaktifkan Interior.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Room selector */}
      <div>
        <label className="mb-1 block text-sm font-medium text-content-primary">Pilih ruangan</label>
        <select
          value={selectedRoom}
          onChange={(e) => setSelectedRoom(e.target.value)}
          className="w-full rounded-md border border-border bg-surface-elevated px-3 py-2 text-sm text-content-primary"
        >
          {rooms.map((r) => (
            <option key={`L${r.level}·${r.name}`} value={r.name}>
              L{r.level} · {r.name}
            </option>
          ))}
        </select>
      </div>

      {/* Style picker */}
      <div>
        <label className="mb-2 block text-sm font-medium text-content-primary">Pilih gaya interior</label>
        <div className="flex flex-wrap gap-2">
          {STYLES.map((s) => (
            <button
              key={s.id}
              type="button"
              aria-pressed={selectedStyle === s.id}
              onClick={() => setSelectedStyle(s.id)}
              className={`rounded-md border px-3 py-2 text-left text-sm transition-colors ${
                selectedStyle === s.id
                  ? 'border-oe-blue bg-oe-blue text-white'
                  : 'border-border bg-surface-elevated text-content-primary hover:bg-surface-secondary'
              }`}
            >
              <div className="font-medium">{s.label}</div>
              <div className={`text-xs ${selectedStyle === s.id ? 'text-white/70' : 'text-content-secondary'}`}>
                {s.desc}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Generate button */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleGenerate}
          disabled={isPending || !selectedRoom}
          className="rounded-md bg-oe-blue px-4 py-2 text-sm font-medium text-white hover:bg-oe-blue-hover disabled:opacity-50"
        >
          {isPending ? 'Merender… (bisa beberapa menit)' : 'Generate Interior'}
        </button>
        {isPending && <Loader2 className="h-5 w-5 animate-spin text-oe-blue" />}
      </div>

      {/* Not-configured banner */}
      {generateState.status === 'not-configured' && (
        <div className="rounded-md border border-border bg-surface-secondary p-4 text-sm text-content-secondary">
          Render service belum dikonfigurasi — set GEMINIGEN_API_KEY di .env.
        </div>
      )}

      {/* No saved layout */}
      {generateState.status === 'no-layout' && (
        <div className="rounded-md border border-border bg-surface-secondary p-4 text-sm text-content-secondary">
          Belum ada denah tersimpan. Selesaikan langkah Konfirmasi dan simpan denah dulu.
        </div>
      )}

      {/* Error */}
      {generateState.status === 'error' && (
        <div className="text-sm text-semantic-error">{generateState.message}</div>
      )}

      {/* Gallery */}
      {interiors.length === 0 && (
        <div className="p-6 text-sm text-content-secondary">
          Belum ada render interior. Pilih ruangan dan gaya, lalu klik "Generate Interior".
        </div>
      )}

      {interiors.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {interiors.map((item) => (
            <div key={item.interior_id} className="rounded-md border border-border p-3">
              {item.status === 'completed' && item.source_url && (
                <img
                  src={item.source_url}
                  alt={`${item.room_name} ${item.style}`}
                  className="mb-2 w-full rounded-md object-cover"
                />
              )}
              {item.status === 'completed' && !item.source_url && (
                <div className="mb-2 flex h-40 items-center justify-center rounded-md bg-surface-secondary text-content-secondary">
                  <ImageOff className="h-6 w-6" />
                  <span className="ml-2 text-xs">tersimpan (tanpa pratinjau)</span>
                </div>
              )}
              {item.status === 'failed' && (
                <div className="mb-2 flex h-40 items-center justify-center rounded-md bg-surface-secondary p-2 text-center text-xs text-semantic-error">
                  {item.error_message ?? 'Render gagal'}
                </div>
              )}
              {item.status !== 'completed' && item.status !== 'failed' && (
                <div className="mb-2 flex h-40 items-center justify-center rounded-md bg-surface-secondary text-content-secondary">
                  <Loader2 className="h-6 w-6 animate-spin" />
                </div>
              )}
              <div className="flex items-center gap-2 text-xs text-content-secondary">
                <span className="font-medium text-content-primary">{item.room_name}</span>
                <span className="rounded bg-surface-secondary px-1.5 py-0.5">{item.style}</span>
                <span className="ml-auto">{STATUS_LABEL[item.status] ?? item.status}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default InteriorStep;
