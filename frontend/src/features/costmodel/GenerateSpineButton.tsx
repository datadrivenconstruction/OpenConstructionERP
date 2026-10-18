// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// GenerateSpineButton - kicks off "generate cost spine from BOQ" and reports
// the created counts via a toast, then invalidates the spine queries so the
// panels re-fetch the freshly built tree.
//
// Positions with no code of the chosen standard land in suspense: their cost
// lines sit on no account. The toast says how many and how much, so the money
// is not silently missing from the structure. A project whose structure is
// already built on another code list answers 409, which is shown as a
// sentence naming both lists.

import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Network } from 'lucide-react';

import { Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { formatCurrency } from '@/shared/lib/money';
import { costModelApi, type SpineGenerationResult } from './api';
import { problemOf } from './structureApi';
import { problemMessage } from './problemMessages';

export interface GenerateSpineButtonProps {
  projectId: string;
  /** Optional BOQ to generate from; omit to let the backend pick the default. */
  boqId?: string;
  /** Code list whose codes the positions are read in; omit for the project default. */
  standard?: string;
  /** Currency for the suspense amount in the toast. */
  currency?: string;
  /** Visual size passed through to the shared Button. */
  size?: 'sm' | 'md';
  /** Visual variant passed through to the shared Button. */
  variant?: 'primary' | 'secondary';
  /** Called with the result after a successful run. */
  onGenerated?: (result: SpineGenerationResult) => void;
}

/**
 * Button that generates the cost spine from a BOQ.
 *
 * On success it shows a toast naming how many control accounts and cost lines
 * were created, and how many positions landed in suspense, then invalidates
 * the ``['spine', projectId]`` and ``['cost-structure', projectId]`` queries.
 * On failure it surfaces the problem sentence (or the error) in a toast.
 */
export function GenerateSpineButton({
  projectId,
  boqId,
  standard,
  currency,
  size = 'sm',
  variant = 'secondary',
  onGenerated,
}: GenerateSpineButtonProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const generate = useMutation({
    // The error is shown here in the user's language; the global toast would repeat it raw.
    meta: { suppressGlobalErrorToast: true },
    mutationFn: () => costModelApi.generateSpine(projectId, { boqId, standard }),
    onSuccess: (result: SpineGenerationResult) => {
      const counts = t('costmodel.spine.generated_counts', {
        defaultValue: '{{accounts}} control accounts and {{lines}} cost lines created.',
        accounts: result?.accounts_created ?? 0,
        lines: result?.cost_lines_created ?? 0,
      });
      const inSuspense = result?.positions_in_suspense ?? 0;
      addToast({
        type: inSuspense > 0 ? 'warning' : 'success',
        title: t('costmodel.spine.generated_title', { defaultValue: 'Cost spine generated' }),
        message:
          inSuspense > 0
            ? `${counts} ${t('costmodel.spine.generated_suspense', {
                defaultValue:
                  'Positions without a code of this list: {{positions}}, worth {{amount}}. Their cost lines sit in suspense until they get a code.',
                positions: inSuspense,
                amount: formatCurrency(result?.suspense_amount ?? '0', currency),
              })}`
            : counts,
      });
      queryClient.invalidateQueries({ queryKey: ['spine', projectId] });
      queryClient.invalidateQueries({ queryKey: ['cost-structure', projectId] });
      onGenerated?.(result);
    },
    onError: (err: unknown) => {
      const problem = problemOf(err);
      addToast({
        type: 'error',
        title: t('costmodel.spine.generate_failed', { defaultValue: 'Failed to generate cost spine' }),
        message: problem ? problemMessage(t, problem.problem, problem.params) : getErrorMessage(err),
      });
    },
  });

  const handleClick = useCallback(() => {
    generate.mutate();
  }, [generate]);

  return (
    <Button
      variant={variant}
      size={size}
      icon={<Network size={size === 'sm' ? 14 : 16} />}
      loading={generate.isPending}
      onClick={handleClick}
    >
      {t('costmodel.spine.generate_cta', { defaultValue: 'Generate from BOQ' })}
    </Button>
  );
}
