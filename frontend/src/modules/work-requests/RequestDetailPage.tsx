// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * /work-requests/:requestId - the same detail the drawer shows, as a page
 * of its own, so a reference can be linked from an email or a standup.
 */

import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useRequestActions } from './actions';
import { RequestDetail } from './RequestDetail';
import { ModuleMissing } from './ModuleMissing';
import { useDepartments, useMe } from './hooks';
import { errorText, isModuleMissing } from './lib';
import './wr.css';

export default function RequestDetailPage() {
  const { t } = useTranslation();
  const { requestId } = useParams<{ requestId: string }>();
  const navigate = useNavigate();
  const departments = useDepartments();
  const me = useMe();
  const go = useCallback((req: { id: string }) => navigate(`/work-requests/${encodeURIComponent(req.id)}`), [navigate]);
  const actions = useRequestActions({ departments: departments.data, me, onOpen: go });

  return (
    <div className="wr mx-auto max-w-4xl">
      <div className="mb-2">
        <Link to="/work-requests" className="wr-btn-quiet">
          ◂ {t('wr.title', { defaultValue: 'Work requests' })}
        </Link>
      </div>
      {departments.isLoading && <p className="wr-hint">{t('wr.loading', { defaultValue: 'Loading…' })}</p>}
      {departments.isError && (isModuleMissing(departments.error) ? <ModuleMissing onRetry={() => void departments.refetch()} /> : <div className="wr-banner err">{errorText(departments.error)}</div>)}
      {departments.data && requestId && (
        <div className="rounded-xl border border-border-light bg-surface-primary">
          <RequestDetail id={requestId} departments={departments.data} me={me} actions={actions} onOpenOther={go} />
        </div>
      )}
      {actions.element}
    </div>
  );
}
