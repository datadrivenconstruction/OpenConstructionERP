// OpenConstructionERP — DataDrivenConstruction (DDC)​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// CWICR AI Estimation Engine — example prompts
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// DDC-CWICR-OE-2026

/**
 * Built-in example prompts for the Quick Estimate flow.
 *
 * Each entry pairs a translation key (for the label shown in the UI) with
 * an English `prompt` string fed straight to the LLM. Prompts stay in
 * English because the underlying models consistently produce richer,
 * more accurate BOQs from English construction descriptions — the label
 * is the only locale-sensitive piece.
 *
 * The list is intentionally short (6 entries) and globally diverse so
 * an estimator can pick one with a single click instead of staring at
 * an empty textarea.
 */

export interface ExamplePrompt {
  /** Stable identifier used as React key and in tests. Lowercase, kebab-case. */
  id: string;
  /** i18next key for the label shown in the example chip. */
  labelKey: string;
  /** Human-readable fallback when the translation is missing. */
  labelFallback: string;
  /**
   * The prompt text inserted into the description textarea. Always English
   * because LLMs produce the best BOQs from English construction descriptions.
   */
  prompt: string;
}

export const EXAMPLE_PROMPTS: readonly ExamplePrompt[] = [
  {
    id: 'apartment-berlin',
    labelKey: 'ai.example_apartment_berlin',
    labelFallback: 'Apartment building, Berlin',
    prompt:
      'Apartment building, 1200 m², Berlin, traditional construction',
  },
  {
    id: 'office-nyc',
    labelKey: 'ai.example_office_nyc',
    labelFallback: 'Office fit-out, NYC',
    prompt:
      'Office fit-out, 800 m², NYC, mid-grade finishes',
  },
  {
    id: 'warehouse-mumbai',
    labelKey: 'ai.example_warehouse_mumbai',
    labelFallback: 'Industrial warehouse, Mumbai',
    prompt:
      'Industrial warehouse, 5000 m², Mumbai, steel frame',
  },
  {
    id: 'school-paris',
    labelKey: 'ai.example_school_paris',
    labelFallback: 'School renovation, Paris',
    prompt:
      'School renovation, 3 floors, 2500 m², Paris, LEED Silver',
  },
  {
    id: 'house-sydney',
    labelKey: 'ai.example_house_sydney',
    labelFallback: 'Single-family house, Sydney',
    prompt:
      'Single-family house, 220 m², Sydney, timber frame',
  },
  {
    id: 'hospital-saopaulo',
    labelKey: 'ai.example_hospital_saopaulo',
    labelFallback: 'Hospital MEP rough-in, São Paulo',
    prompt:
      'Hospital MEP rough-in, 800 beds, São Paulo',
  },
] as const;

/** Returns the prompt for the given id, or `undefined` when no match. */
export function getExamplePromptById(id: string): ExamplePrompt | undefined {
  return EXAMPLE_PROMPTS.find((p) => p.id === id);
}
