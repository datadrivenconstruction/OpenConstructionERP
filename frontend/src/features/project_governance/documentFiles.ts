// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Putting a file behind a frame document.
//
// A frame document carries no file itself. It points at a CDE container, and
// the container's current revision is the file a gate reviews. So "attach a
// file" is four calls: upload the file to the project's documents, make sure
// the frame document has a container, add the file to that container as a
// revision, and point the frame document at the container. A document that
// already has a container only gets the new revision.

import { createCDEContainer, createContainerRevision, type CDEContainer } from '@/features/cde/api';
import { uploadDocument } from '@/features/documents/api';

import { attachDocument, type FrameDocument } from './api';

/**
 * The CDE code of the container made for a frame document.
 *
 * A project tracks one document per area and type, so the pair names the
 * container uniquely, and a second try after a failed step finds the
 * container the first try made instead of colliding with it.
 */
export function frameContainerCode(areaCode: string, docType: string): string {
  return ['FRAME', areaCode, docType]
    .map((part) => part.trim().toUpperCase().replace(/[^A-Z0-9]+/g, '-'))
    .join('-');
}

export interface AttachFileArgs {
  projectId: string;
  doc: Pick<FrameDocument, 'id' | 'doc_type' | 'container_id'>;
  areaCode: string;
  /** The document's name as the reader sees it, used as the new container's title. */
  title: string;
  file: File;
  /** The project's containers as already loaded, to reuse the one an earlier try created. */
  containers: CDEContainer[];
}

/** Upload `file` and make it the newest revision behind the frame document. Returns the container id. */
export async function attachFileToDocument(args: AttachFileArgs): Promise<string> {
  const { projectId, doc, areaCode, title, file, containers } = args;
  const uploaded = await uploadDocument(projectId, file, 'other');
  let containerId = doc.container_id;
  if (!containerId) {
    const code = frameContainerCode(areaCode, doc.doc_type);
    const existing = containers.find((c) => c.container_code === code);
    containerId = (existing ?? (await createCDEContainer({ project_id: projectId, container_code: code, title }))).id;
  }
  await createContainerRevision(containerId, {
    file_name: file.name,
    document_id: uploaded.id,
    mime_type: file.type || undefined,
    file_size: String(file.size),
  });
  if (!doc.container_id) await attachDocument(projectId, doc.id, containerId);
  return containerId;
}
