// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Readiness probe for the AI Estimate Builder. Surfaces both gates the
// dossier requires before the run can be a fully precise estimate:
//   1. an LLM provider key (or local base url) - drives understanding,
//      grouping and the per-group reasoning loop.
//   2. the vector DB (Qdrant) - drives grounded rate retrieval.
//
// Neither is hard-required: the module degrades gracefully (deterministic
// extraction + signature grouping + lexical rate lookup) and this hook
// reports exactly which capability is missing so the UI can guide the
// user instead of failing.

import { useQuery } from '@tanstack/react-query';
import { aiApi, type AISettings } from '@/features/ai/api';
import { aiEstimatorApi } from './api';

/** True when the user has any usable LLM provider configured. */
export function hasLlmKey(settings: AISettings | undefined): boolean {
  if (!settings) return false;
  const keyFlags: (keyof AISettings)[] = [
    'anthropic_api_key_set',
    'openai_api_key_set',
    'gemini_api_key_set',
    'openrouter_api_key_set',
    'mistral_api_key_set',
    'groq_api_key_set',
    'deepseek_api_key_set',
    'together_api_key_set',
    'fireworks_api_key_set',
    'perplexity_api_key_set',
    'cohere_api_key_set',
    'ai21_api_key_set',
    'xai_api_key_set',
    'zhipu_api_key_set',
    'baidu_api_key_set',
    'yandex_api_key_set',
    'gigachat_api_key_set',
    'kimi_api_key_set',
  ];
  if (keyFlags.some((k) => settings[k] === true)) return true;
  // Local runtimes only count when a base url is configured.
  return Boolean(settings.ollama_base_url) || Boolean(settings.vllm_base_url);
}

export interface AiReadiness {
  /** LLM key present -> AI understanding / grouping / reasoning available. */
  llmReady: boolean;
  /** Vector DB reachable -> grounded semantic rate retrieval available. */
  vectorReady: boolean;
  /** The preferred model id the run would use, if known. */
  preferredModel: string | null;
  isLoading: boolean;
}

/** Probe both gates. Errors degrade to "not ready" rather than throwing,
 *  so the page renders its guidance card instead of an error boundary. */
export function useAiReadiness(): AiReadiness {
  const settingsQ = useQuery({
    queryKey: ['ai-settings'],
    queryFn: aiApi.getSettings,
    staleTime: 60_000,
    retry: false,
  });

  const qdrantQ = useQuery({
    queryKey: ['ai-estimator-qdrant-health'],
    queryFn: aiEstimatorApi.qdrantHealth,
    staleTime: 30_000,
    retry: false,
  });

  const health = qdrantQ.data;
  const vectorReady = Boolean(
    health?.reachable === true ||
      (typeof health?.status === 'string' && health.status.toLowerCase() === 'ok'),
  );

  return {
    llmReady: hasLlmKey(settingsQ.data),
    vectorReady,
    preferredModel: settingsQ.data?.preferred_model || null,
    isLoading: settingsQ.isLoading || qdrantQ.isLoading,
  };
}
