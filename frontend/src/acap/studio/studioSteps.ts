export const STEP_COUNT = 7;

export const STEP_TITLES = [
  'Upload Gambar',
  'AI Extract',
  'Konfirmasi',
  'RAB',
  'Timeline',
  '3D',
  'Interior',
] as const;

export const MAX_STEP_WITHOUT_LAYOUT = 3;
export const MAX_STEP_WITH_LAYOUT = 7;

export interface StepAvailability {
  maxStep: number;
}

export function deriveStepAvailability(input: { hasLayout: boolean }): StepAvailability {
  return { maxStep: input.hasLayout ? MAX_STEP_WITH_LAYOUT : MAX_STEP_WITHOUT_LAYOUT };
}