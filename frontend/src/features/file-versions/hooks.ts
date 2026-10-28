// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** React Query hooks for File Versioning. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { fileVersionKeys, listVersions, restoreVersion } from './api';
import type { FileKind, FileVersionResponse } from './types';

/** Load the version chain for a file. */
export function useFileVersions(
  fileId: string | null | undefined,
  kind: FileKind | null | undefined,
) {
  return useQuery<FileVersionResponse[]>({
    queryKey: [fileVersionKeys.list, fileId, kind],
    queryFn: () => listVersions(fileId as string, kind as FileKind),
    enabled: Boolean(fileId) && Boolean(kind),
    staleTime: 30_000,
  });
}

/** Restore a version + invalidate the chain list. */
export function useRestoreVersion(
  fileId: string | null | undefined,
  kind: FileKind | null | undefined,
) {
  const qc = useQueryClient();
  return useMutation<FileVersionResponse, Error, string>({
    mutationFn: (versionId: string) => restoreVersion(versionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [fileVersionKeys.list, fileId, kind] });
    },
  });
}
