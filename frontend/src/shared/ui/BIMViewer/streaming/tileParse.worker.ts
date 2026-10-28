// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * Off-main-thread GLB tile parser.
 *
 * Receives a tile's GLB ArrayBuffer, runs GLTFLoader.parse here (off the UI
 * thread), and posts back the parsed scene serialized with three's own
 * Object3D.toJSON(). The main thread reconstructs it with THREE.ObjectLoader,
 * so hierarchy, node NAMES and materials are round-tripped by three itself -
 * never hand-rebuilt - which keeps the viewer's node-name -> element-id match
 * intact.
 *
 * This worker only ever REPLIES; it never throws across the boundary. Any
 * failure (bad bytes, a GLTFLoader error, a toJSON error) comes back as
 * { ok: false } so the main thread can fall back to a main-thread parse.
 */

import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import type { GLTF } from 'three/addons/loaders/GLTFLoader.js';

import type { ParseRequest, ParseResponse } from './workerTileParser';

// Minimal worker-global typing so this file does not depend on the TS
// "webworker" lib being in the project's compilation.
const ctx = self as unknown as {
  onmessage: ((event: MessageEvent<ParseRequest>) => void) | null;
  postMessage: (message: ParseResponse) => void;
};

const loader = new GLTFLoader();

ctx.onmessage = (event: MessageEvent<ParseRequest>): void => {
  const { id, buffer } = event.data;
  const fail = (): void => ctx.postMessage({ id, ok: false });
  try {
    loader.parse(
      buffer,
      '',
      (gltf: GLTF) => {
        try {
          // Capture the node-name set the parse produced (the exact keys the
          // viewer's mesh -> element match walks) so the main thread can verify
          // the toJSON/ObjectLoader round-trip preserved every one of them.
          const names: string[] = [];
          gltf.scene.traverse((object) => {
            if (object.name) names.push(object.name);
          });
          ctx.postMessage({ id, ok: true, json: gltf.scene.toJSON(), names });
        } catch {
          fail();
        }
      },
      () => fail(),
    );
  } catch {
    fail();
  }
};
