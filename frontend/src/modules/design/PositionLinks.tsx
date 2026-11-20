// Design module (ERP side of the design editor link).
/**
 * From an estimate position to where it lives: the elements behind it in the ERP model viewer (isolated), the row
 * in the BOQ (highlighted), the elements in the design editor (selected). Resolved on click, one request.
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Box, PencilRuler, Table2 } from 'lucide-react';
import { getErrorMessage } from '@/shared/lib/api';
import { tr } from './BriefFields';
import { boqUrl, editorUrl, fetchPositionElements, viewerUrl, type PositionElements } from './linksApi';

type Target = 'model' | 'boq' | 'editor';

export function PositionLinks({ projectId, positionId, rule }: { projectId: string; positionId: string; rule: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<Target | null>(null);
  const [error, setError] = useState<string | null>(null);

  const go = async (target: Target) => {
    setBusy(target);
    setError(null);
    try {
      const e: PositionElements = await fetchPositionElements(projectId, positionId);
      const url = target === 'boq' ? boqUrl(e) : target === 'editor' ? editorUrl(e.keys) : viewerUrl(projectId, e);
      if (!url || (target !== 'boq' && e.keys.length === 0)) setError(tr(t, 'design.links.no_elements'));
      else navigate(url);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };
  const btn = 'inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-oe-blue-text hover:bg-surface-secondary hover:underline disabled:opacity-50';
  return (
    <div className="flex flex-wrap items-center gap-1" data-testid={`links-${rule}`}>
      <button type="button" className={btn} disabled={busy !== null} onClick={() => void go('model')} data-testid={`show-model-${rule}`}>
        <Box size={12} aria-hidden /> {tr(t, 'design.links.show_in_model')}
      </button>
      <button type="button" className={btn} disabled={busy !== null} onClick={() => void go('boq')} data-testid={`show-boq-${rule}`}>
        <Table2 size={12} aria-hidden /> {tr(t, 'design.links.open_in_boq')}
      </button>
      <button type="button" className={btn} disabled={busy !== null} onClick={() => void go('editor')} data-testid={`show-editor-${rule}`}>
        <PencilRuler size={12} aria-hidden /> {tr(t, 'design.links.select_in_editor')}
      </button>
      {error && <span role="alert" className="text-xs text-semantic-error">{error}</span>}
    </div>
  );
}
