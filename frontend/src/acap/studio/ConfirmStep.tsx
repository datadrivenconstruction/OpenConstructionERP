import { useCallback, useState } from 'react';
import type { FloorPlan, RoomType, Point } from '@/acap/planTypes';
import { FloorPlanEditor } from '@/acap/FloorPlanEditor';
import { saveLayout, LayoutValidationApiError } from '@/acap/floorPlanApi';
import { rectToPolygon } from '@/acap/serialize';

const ROOM_TYPE_OPTIONS: RoomType[] = [
  'kamar_tidur_utama', 'kamar_tidur', 'kamar_mandi', 'dapur',
  'ruang_tamu', 'ruang_keluarga', 'ruang_makan', 'carport', 'garasi',
  'musholla', 'gudang', 'teras', 'taman', 'sirkulasi', 'other',
];

interface ConfirmStepProps {
  draft: FloorPlan;
  onDraftChange: (plan: FloorPlan) => void;
  projectId: string;
  onSaved: (version: number) => void;
}

export function rectRoom(x: number, y: number, w: number, l: number): { polygon: Point[]; area_m2: number } {
  return { polygon: rectToPolygon(x, y, w, l), area_m2: Math.round(w * l * 1000) / 1000 };
}

export function ConfirmStep({ draft, onDraftChange, projectId, onSaved }: ConfirmStepProps) {
  const [showEditor, setShowEditor] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveErrors, setSaveErrors] = useState<string[] | null>(null);
  const [savedVersion, setSavedVersion] = useState<number | null>(null);

  const handleRoomChange = useCallback(
    (levelIndex: number, roomIndex: number, field: string, value: string | number) => {
      const levels = draft.levels.map((level, li) => {
        if (li !== levelIndex) return level;
        return {
          ...level,
          rooms: level.rooms.map((room, ri) => {
            if (ri !== roomIndex) return room;

            if (field === 'name') {
              return { ...room, name: String(value) };
            }
            if (field === 'type') {
              return { ...room, type: value as RoomType };
            }

            const rect = { x: room.polygon[0]?.x ?? 0, y: room.polygon[0]?.y ?? 0, w: 0, h: 0 };
            const xs = room.polygon.map((p) => p.x);
            const ys = room.polygon.map((p) => p.y);
            rect.x = Math.min(...xs);
            rect.y = Math.min(...ys);
            rect.w = Math.max(...xs) - rect.x;
            rect.h = Math.max(...ys) - rect.y;

            if (field === 'x') rect.x = Number(value);
            else if (field === 'y') rect.y = Number(value);
            else if (field === 'width_m') rect.w = Number(value);
            else if (field === 'length_m') rect.h = Number(value);

            const { polygon, area_m2 } = rectRoom(rect.x, rect.y, rect.w, rect.h);
            return { ...room, polygon, area_m2 };
          }),
        };
      });

      onDraftChange({ ...draft, levels });
    },
    [draft, onDraftChange],
  );

  const handleSave = useCallback(async () => {
    setSaving(true);
    setSaveErrors(null);
    try {
      const resp = await saveLayout(projectId, draft);
      setSavedVersion(resp.version);
      onSaved(resp.version);
    } catch (err) {
      if (err instanceof LayoutValidationApiError) {
        setSaveErrors(err.reasons);
      } else {
        setSaveErrors([err instanceof Error ? err.message : 'Gagal menyimpan layout']);
      }
    } finally {
      setSaving(false);
    }
  }, [projectId, draft, onSaved]);

  return (
    <div className="flex flex-col gap-4">
      {draft.levels.map((level, li) => (
        <div key={li}>
          <h3 className="mb-2 text-sm font-semibold text-content-primary">Lantai {level.level}</h3>
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border bg-surface-secondary text-content-secondary">
                  <th className="p-2">Nama</th>
                  <th className="p-2">Tipe</th>
                  <th className="p-2">X (m)</th>
                  <th className="p-2">Y (m)</th>
                  <th className="p-2">Lebar (m)</th>
                  <th className="p-2">Panjang (m)</th>
                  <th className="p-2">Luas (m²)</th>
                </tr>
              </thead>
              <tbody>
                {level.rooms.map((room, ri) => {
                  const xs = room.polygon.map((p) => p.x);
                  const ys = room.polygon.map((p) => p.y);
                  const rx = Math.min(...xs);
                  const ry = Math.min(...ys);
                  const rw = Math.max(...xs) - rx;
                  const rh = Math.max(...ys) - ry;

                  return (
                    <tr key={ri} className="border-b border-border-light">
                      <td className="p-2">
                        <input
                          type="text"
                          value={room.name}
                          onChange={(e) => handleRoomChange(li, ri, 'name', e.target.value)}
                          className="w-full rounded border border-border bg-surface-elevated p-1 text-sm"
                        />
                      </td>
                      <td className="p-2">
                        <select
                          value={room.type}
                          onChange={(e) => handleRoomChange(li, ri, 'type', e.target.value)}
                          className="w-full rounded border border-border bg-surface-elevated p-1 text-sm"
                        >
                          {ROOM_TYPE_OPTIONS.map((t) => (
                            <option key={t} value={t}>{t}</option>
                          ))}
                        </select>
                      </td>
                      <td className="p-2">
                        <input
                          type="number"
                          step="0.01"
                          value={rx}
                          onChange={(e) => handleRoomChange(li, ri, 'x', e.target.value)}
                          className="w-20 rounded border border-border bg-surface-elevated p-1 text-sm"
                        />
                      </td>
                      <td className="p-2">
                        <input
                          type="number"
                          step="0.01"
                          value={ry}
                          onChange={(e) => handleRoomChange(li, ri, 'y', e.target.value)}
                          className="w-20 rounded border border-border bg-surface-elevated p-1 text-sm"
                        />
                      </td>
                      <td className="p-2">
                        <input
                          type="number"
                          step="0.01"
                          value={rw}
                          onChange={(e) => handleRoomChange(li, ri, 'width_m', e.target.value)}
                          className="w-20 rounded border border-border bg-surface-elevated p-1 text-sm"
                        />
                      </td>
                      <td className="p-2">
                        <input
                          type="number"
                          step="0.01"
                          value={rh}
                          onChange={(e) => handleRoomChange(li, ri, 'length_m', e.target.value)}
                          className="w-20 rounded border border-border bg-surface-elevated p-1 text-sm"
                        />
                      </td>
                      <td className="p-2 text-content-secondary">{room.area_m2.toFixed(3)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setShowEditor((s) => !s)}
          className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary"
        >
          {showEditor ? 'Tutup Editor 2D' : 'Editor 2D'}
        </button>
      </div>

      {showEditor && (
        <FloorPlanEditor
          plan={draft}
          onChange={onDraftChange}
          onSave={handleSave}
          saving={saving}
          saveErrors={saveErrors}
          savedVersion={savedVersion}
        />
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="rounded-md bg-oe-blue px-4 py-2 text-sm font-medium text-white hover:bg-oe-blue-hover disabled:opacity-50"
        >
          {saving ? 'Menyimpan…' : 'Simpan Layout'}
        </button>
        {savedVersion != null && !saveErrors && (
          <span className="text-sm text-semantic-success">Tersimpan (versi {savedVersion})</span>
        )}
      </div>

      {saveErrors && saveErrors.length > 0 && (
        <div className="rounded-md border border-semantic-error bg-semantic-error-bg p-3 text-sm text-semantic-error">
          <p className="font-medium">Layout tidak valid:</p>
          <ul className="mt-1 list-disc pl-5">
            {saveErrors.map((reason, i) => (
              <li key={i}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default ConfirmStep;
