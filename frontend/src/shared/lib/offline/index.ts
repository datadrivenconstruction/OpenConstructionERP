// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Offline slice for the field PWA (TOP-30 #14).
 *
 * Public surface:
 *   - connectivity        online/offline detection (framework-light store)
 *   - mutationQueue       storage-agnostic, idempotent, ordered replay queue
 *   - fieldQueue          the concrete field queue + HTTP sender wiring
 *   - registerFieldSW     scoped service-worker registration helper
 *   - offlineStore        device-side records + photo Blobs (IndexedDB / memory)
 *   - threeWayMerge       pure merge of an offline edit against the server copy
 *   - recordSync          sync engine for diaries, punch items and inspections
 *   - useOfflineSync      React hook + store behind the sync status pill
 */

export {
  isOnline,
  subscribeConnectivity,
  emitConnectivityForTests,
  type ConnectivityListener,
} from './connectivity';

export {
  MutationQueue,
  sortByFifo,
  newClientOpId,
  createMemoryQueueStorage,
  createIndexedDbQueueStorage,
  type QueuedOp,
  type QueueStorage,
  type OpSender,
  type ReplayOutcome,
  type DrainResult,
  type DrainSummary,
  type EnqueueInput,
  type HttpMethod,
  type MutationQueueOptions,
  type BackoffOptions,
  type MergeConflictInfo,
  computeBackoffDelay,
  DEFAULT_BACKOFF,
} from './mutationQueue';

export {
  getFieldQueue,
  createFieldSender,
  pickQueueStorage,
  resetFieldQueueForTests,
  type FieldHeadersProvider,
} from './fieldQueue';

export {
  getOfflineStore,
  createMemoryOfflineStore,
  createIndexedDbOfflineStore,
  newLocalId,
  isLocalId,
  type OfflineStore,
  type OfflineEntityKind,
  type LocalRecord,
  type PhotoBlobRecord,
} from './offlineStore';

export {
  computeThreeWayMerge,
  applyDecisions,
  type ThreeWayMergeResult,
  type MergeConflict,
  type ConflictDecisions,
} from './threeWayMerge';

export {
  useOfflineSyncStore,
  deriveSyncStatus,
  type OfflineSyncStatus,
  type OfflineSyncState,
} from './offlineSyncStore';

export {
  createRecordSender,
  classifyConflictBody,
  isNetworkError,
  queueCreate,
  queueUpdate,
  queuePhoto,
  overlayRecords,
  runSync,
  getRecordQueue,
} from './recordSync';

export { useOfflineSync, useOfflineSyncLoop, useOfflineRecords } from './useOfflineSync';

export {
  registerFieldServiceWorker,
  unregisterFieldServiceWorker,
  type RegisterFieldSWResult,
} from './registerFieldSW';
