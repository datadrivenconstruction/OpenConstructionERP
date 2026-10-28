// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Basis of Estimate - standalone page host.
 *
 * The estimate-basis feature ships its working surface as an embeddable
 * `EstimateBasisPanel` (project + BOQ scoped). This thin page wires it to the
 * active project context so it is reachable as its own route, matching how the
 * other project-scoped estimating tools are mounted.
 */

import { useTranslation } from 'react-i18next';
import { CollapsibleSection, PageHeader } from '@/shared/ui';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { EstimateBasisPanel } from './EstimateBasisPanel';
import { HowBasisWorks } from './HowBasisWorks';

export function EstimateBasisPage() {
  const { t } = useTranslation();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeBOQId = useProjectContextStore((s) => s.activeBOQId);

  // The `defaultValue` below matches `estimate_basis.subtitle` in the locale
  // files verbatim. A key the locales already carry ignores whatever default
  // the code passes, so the two must not be allowed to drift: a reworded
  // default here would read as a change and show nothing.
  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        srTitle={t('estimate_basis.title', { defaultValue: 'Basis of Estimate' })}
        subtitle={t('estimate_basis.subtitle', {
          defaultValue:
            'Draft the inclusions, exclusions, assumptions and pricing basis behind the estimate, so a reviewer can see what the number does and does not cover.',
        })}
      />
      {/* Collapsible, like every other module explainer: helpful the first time,
          and in the way once you know the module. It used to sit open above the
          document permanently, which pushed the estimate's own figure below the
          fold on the screen whose whole job is to carry it. */}
      <CollapsibleSection
        storageKey="estimate_basis.how"
        title={t('estimate_basis.flow_title', { defaultValue: 'How the Basis of Estimate fits together' })}
      >
        <HowBasisWorks />
      </CollapsibleSection>
      {/* No currency prop: the document resolves the project's own currency
          server-side. Passing it here was the older shape and this page never
          had one to pass, which is exactly why its figures used to render
          without a symbol. */}
      {activeProjectId ? (
        <EstimateBasisPanel projectId={activeProjectId} boqId={activeBOQId} />
      ) : (
        <RequiresProject>{null}</RequiresProject>
      )}
    </div>
  );
}
