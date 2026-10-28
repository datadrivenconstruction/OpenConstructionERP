// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * React Query mutation for building a priced assembly from a production norm.
 *
 * Kept separate from the page so the panel stays declarative and the caller
 * owns the side effects (toast, showing the build-up). The response money /
 * factor fields are Decimal-as-string and are handed through untouched.
 */
import { useMutation } from '@tanstack/react-query';

import {
  buildAssemblyFromNorm,
  type BuildAssemblyPayload,
  type BuildAssemblyResult,
} from './api';

/** Variables for one build-assembly run: the source norm and the request body. */
export interface BuildAssemblyVars {
  normId: string;
  body: BuildAssemblyPayload;
}

/**
 * Mutation hook that builds and saves a priced assembly from a norm.
 *
 * Success and error handling are left to the caller's `mutate` options so the
 * hook is reusable outside the Production Norms page.
 */
export function useBuildAssembly() {
  return useMutation<BuildAssemblyResult, unknown, BuildAssemblyVars>({
    mutationFn: ({ normId, body }) => buildAssemblyFromNorm(normId, body),
  });
}
