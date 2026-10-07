// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The second door to the semantic-search model, for anyone who skipped it in
// the setup wizard. The download never starts unasked, so without this card a
// user who clicked through the wizard would have no way to get it later.
// Flipping the switch is the request: it calls the install endpoint at once,
// and the card then shows progress from the status poll.

import { useCallback, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { aiEstimatorApi } from '@/features/ai-estimator/api';
import { SemanticModelCard } from '@/features/onboarding/SemanticModelCard';

export default function SemanticModelSettings() {
  const qc = useQueryClient();
  const [requested, setRequested] = useState(false);

  const handleToggle = useCallback(
    (next: boolean) => {
      if (!next) return;
      setRequested(true);
      void aiEstimatorApi
        .installEmbeddingModel()
        .catch(() => undefined)
        .finally(() => {
          void qc.invalidateQueries({ queryKey: ['embedding-model-status'] });
        });
    },
    [qc],
  );

  return <SemanticModelCard enabled={requested} onToggle={handleToggle} />;
}
