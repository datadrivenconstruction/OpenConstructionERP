// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

export {
  IATE_ALLOWED_PREFIXES,
  isIateUrlAllowed,
  getTranslationStatus,
  triggerLookupDownload,
  translateOne,
} from './api';

export {
  TRANSLATION_STATUS_QUERY_KEY,
  useTranslationStatus,
  useTriggerDownload,
  useTranslateOne,
} from './queries';

export { TranslationSettingsTab } from './TranslationSettingsTab';

export type {
  CacheStats,
  DictionaryEntry,
  DownloadRequestBody,
  DownloadResponse,
  InFlightTask,
  LookupKind,
  StatusResponse,
  TranslateRequestBody,
  TranslateResponse,
  TranslationTier,
} from './types';
