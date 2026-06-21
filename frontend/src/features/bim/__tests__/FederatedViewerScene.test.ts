// @ts-nocheck
/**
 * FederatedViewerScene tests - BIM Federations Slice 3.
 *
 * Counter-intuitive design note
 * -----------------------------
 * jsdom has no WebGL context, so we mock ``THREE.WebGLRenderer`` and
 * ``GLTFLoader``. The rest of three.js (``Scene``, ``Group``, ``Mesh``,
 * ``Material``) is pure JS and runs in jsdom unchanged.
 *
 * GLTFLoader mocking strategy:
 *   We mock ``three/examples/jsm/loaders/GLTFLoader.js`` to expose a
 *   ``GLTFLoader`` class whose ``parse(buffer, _path, onLoad, _onError)``
 *   invokes ``onLoad`` with a pre-built scene that the test stages via
 *   ``__setNextGLTF(scene)`` BEFORE calling ``scene.addMember``. This
 *   gives each test full control over the mesh tree, IfcClass userData,
 *   and material count without parsing real GLB bytes.
 */
import {
  describe,
  expect,
  it,
  vi,
  beforeEach,
  afterEach,
} from 'vitest';
import * as THREE from 'three';

/* ── Three.js mocks ─────────────────────────────────────────────────── */

// Track the "next gltf.scene" that GLTFLoader.parse() should yield.
let nextGltfScene: THREE.Group | null = null;
let nextParseError: Error | null = null;
function __setNextGLTF(scene: THREE.Group): void {
  nextGltfScene = scene;
  nextParseError = null;
}
function __setNextGLTFError(err: Error): void {
  nextGltfScene = null;
  nextParseError = err;
}

vi.mock('three/examples/jsm/loaders/GLTFLoader.js', () => {
  class FakeGLTFLoader {
    parse(
      _buffer: ArrayBuffer,
      _path: string,
      onLoad: (gltf: { scene: THREE.Group }) => void,
      onError: (err: Error) => void,
    ): void {
      if (nextParseError) {
        onError(nextParseError);
        return;
      }
      const scene = nextGltfScene ?? new THREE.Group();
      onLoad({ scene });
    }
  }
  return { GLTFLoader: FakeGLTFLoader };
});

vi.mock('three/examples/jsm/controls/OrbitControls.js', () => {
  class FakeOrbitControls {
    target = new THREE.Vector3();
    enableDamping = false;
    dampingFactor = 0;
    rotateSpeed = 0;
    panSpeed = 0;
    zoomSpeed = 0;
    minDistance = 0;
    maxDistance = 0;
    minPolarAngle = 0;
    maxPolarAngle = Math.PI;
    private listeners: Record<string, Array<() => void>> = {};
    constructor(_camera: unknown, _dom: HTMLElement) {}
    update(): boolean {
      return false;
    }
    addEventListener(type: string, cb: () => void): void {
      (this.listeners[type] ??= []).push(cb);
    }
    dispose(): void {}
  }
  return { OrbitControls: FakeOrbitControls };
});

vi.mock('three', async () => {
  const actual = await vi.importActual<typeof import('three')>('three');
  class FakeWebGLRenderer {
    domElement: HTMLCanvasElement;
    shadowMap = { enabled: false };
    toneMapping = 0;
    toneMappingExposure = 1;
    constructor(opts: { canvas?: HTMLCanvasElement } = {}) {
      this.domElement =
        opts.canvas ?? (document.createElement('canvas') as HTMLCanvasElement);
    }
    setPixelRatio(): void {}
    setSize(): void {}
    setClearColor(): void {}
    render(): void {}
    dispose(): void {}
  }
  return {
    ...actual,
    WebGLRenderer: FakeWebGLRenderer,
  };
});

/* ── Helpers ────────────────────────────────────────────────────────── */

function mountCanvas(): HTMLCanvasElement {
  const wrap = document.createElement('div');
  Object.defineProperty(wrap, 'clientWidth', { value: 800, configurable: true });
  Object.defineProperty(wrap, 'clientHeight', {
    value: 600,
    configurable: true,
  });
  const canvas = document.createElement('canvas');
  wrap.appendChild(canvas);
  document.body.appendChild(wrap);
  return canvas;
}

function makeMember(ifcClasses: string[]): THREE.Group {
  const root = new THREE.Group();
  for (const cls of ifcClasses) {
    const geom = new THREE.BoxGeometry(1, 1, 1);
    const mat = new THREE.MeshStandardMaterial({ color: 0x888888 });
    const mesh = new THREE.Mesh(geom, mat);
    mesh.name = `${cls}_001`;
    root.add(mesh);
  }
  return root;
}

// jsdom returns null from canvas.getContext('webgl2'), which the scene's
// canUseWebGL2() guard reads as "no WebGL2" and would make the constructor
// throw WebGLUnavailableError. The WebGLRenderer itself is already mocked, so
// stub getContext to report a usable context for the webgl2 probe and keep the
// happy-path tests exercising the real construction flow.
let _origGetContext: typeof HTMLCanvasElement.prototype.getContext;

// Force-stub rAF so animate() loop does not retain timers across tests.
beforeEach(() => {
  vi.stubGlobal('requestAnimationFrame', (() => 0) as unknown as typeof requestAnimationFrame);
  vi.stubGlobal('cancelAnimationFrame', (() => undefined) as unknown as typeof cancelAnimationFrame);
  _origGetContext = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function getContext(
    this: HTMLCanvasElement,
    contextId: string,
    ...rest: unknown[]
  ) {
    if (contextId === 'webgl2' || contextId === 'webgl') {
      return {} as unknown as RenderingContext;
    }
    return _origGetContext.call(this, contextId, ...rest);
  } as typeof HTMLCanvasElement.prototype.getContext;
  nextGltfScene = null;
  nextParseError = null;
});

afterEach(() => {
  vi.unstubAllGlobals();
  HTMLCanvasElement.prototype.getContext = _origGetContext;
  document.body.innerHTML = '';
});

/* ── Tests ──────────────────────────────────────────────────────────── */

describe('FederatedViewerScene', () => {
  it('constructor creates root Group named "federation-root"', async () => {
    const { FederatedViewerScene } = await import('../FederatedViewerScene');
    const scene = new FederatedViewerScene(mountCanvas());
    expect(scene.root).toBeInstanceOf(THREE.Group);
    expect(scene.root.name).toBe('federation-root');
    expect(scene.scene.children).toContain(scene.root);
    scene.dispose();
  });

  it('addMember creates a Group named "member-{id}" under root', async () => {
    const { FederatedViewerScene } = await import('../FederatedViewerScene');
    const scene = new FederatedViewerScene(mountCanvas());
    __setNextGLTF(makeMember(['IfcWall', 'IfcWall']));
    await scene.addMember({
      modelId: 'mod-a',
      discipline: 'arch',
      glbBuffer: new ArrayBuffer(8),
      originOffset: { x: 1, y: 2, z: 3 },
    });
    const memberGroup = scene.getMemberGroup('mod-a');
    expect(memberGroup).toBeDefined();
    expect(memberGroup!.name).toBe('member-mod-a');
    expect(memberGroup!.parent).toBe(scene.root);
    expect(memberGroup!.position.x).toBe(1);
    expect(memberGroup!.position.y).toBe(2);
    expect(memberGroup!.position.z).toBe(3);
    expect(scene.getMemberCount()).toBe(1);
    scene.dispose();
  });

  it('addMember does NOT share material instances across members', async () => {
    const { FederatedViewerScene } = await import('../FederatedViewerScene');
    const scene = new FederatedViewerScene(mountCanvas());

    __setNextGLTF(makeMember(['IfcWall']));
    await scene.addMember({
      modelId: 'mod-a',
      discipline: 'arch',
      glbBuffer: new ArrayBuffer(8),
      originOffset: { x: 0, y: 0, z: 0 },
    });
    __setNextGLTF(makeMember(['IfcWall']));
    await scene.addMember({
      modelId: 'mod-b',
      discipline: 'struct',
      glbBuffer: new ArrayBuffer(8),
      originOffset: { x: 0, y: 0, z: 0 },
    });

    // Turn on discipline coloring - that's when materials get CLONED per
    // the lazy-clone contract.
    scene.setDisciplineColoringEnabled(true);

    const a = scene.getMemberGroup('mod-a')!;
    const b = scene.getMemberGroup('mod-b')!;
    let aMat: THREE.Material | null = null;
    let bMat: THREE.Material | null = null;
    a.traverse((o) => {
      if (o instanceof THREE.Mesh && !aMat)
        aMat = Array.isArray(o.material) ? o.material[0] : o.material;
    });
    b.traverse((o) => {
      if (o instanceof THREE.Mesh && !bMat)
        bMat = Array.isArray(o.material) ? o.material[0] : o.material;
    });
    expect(aMat).not.toBeNull();
    expect(bMat).not.toBeNull();
    expect(aMat).not.toBe(bMat); // independent clones
    scene.dispose();
  });

  it('setDisciplineColoringEnabled(true) overrides material colors with palette', async () => {
    const { FederatedViewerScene, DISCIPLINE_PALETTE } = await import(
      '../FederatedViewerScene'
    );
    const scene = new FederatedViewerScene(mountCanvas());
    __setNextGLTF(makeMember(['IfcWall']));
    await scene.addMember({
      modelId: 'mod-arch',
      discipline: 'arch',
      glbBuffer: new ArrayBuffer(8),
      originOffset: { x: 0, y: 0, z: 0 },
    });

    scene.setDisciplineColoringEnabled(true);
    expect(scene.isDisciplineColoringEnabled()).toBe(true);

    const expected = new THREE.Color(DISCIPLINE_PALETTE.arch);
    const member = scene.getMemberGroup('mod-arch')!;
    let observed: THREE.Color | null = null;
    member.traverse((o) => {
      if (o instanceof THREE.Mesh) {
        const m = Array.isArray(o.material) ? o.material[0] : o.material;
        if (!observed && (m as THREE.MeshStandardMaterial).color)
          observed = (m as THREE.MeshStandardMaterial).color;
      }
    });
    expect(observed).not.toBeNull();
    expect(observed!.getHexString()).toBe(expected.getHexString());
    scene.dispose();
  });

  it('setDisciplineColoringEnabled(false) restores originals', async () => {
    const { FederatedViewerScene } = await import('../FederatedViewerScene');
    const scene = new FederatedViewerScene(mountCanvas());

    // Stage a member whose source material starts at a known color.
    const root = new THREE.Group();
    const originalColor = new THREE.Color(0x123456);
    const mat = new THREE.MeshStandardMaterial({ color: originalColor.clone() });
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), mat);
    mesh.name = 'IfcWall_001';
    root.add(mesh);
    __setNextGLTF(root);

    await scene.addMember({
      modelId: 'mod-a',
      discipline: 'arch',
      glbBuffer: new ArrayBuffer(8),
      originOffset: { x: 0, y: 0, z: 0 },
    });

    scene.setDisciplineColoringEnabled(true);
    scene.setDisciplineColoringEnabled(false);
    expect(scene.isDisciplineColoringEnabled()).toBe(false);

    // After restore, the live mesh.material reference should be the
    // original instance we created above, with the original color.
    const member = scene.getMemberGroup('mod-a')!;
    let live: THREE.MeshStandardMaterial | null = null;
    member.traverse((o) => {
      if (o instanceof THREE.Mesh && !live)
        live = (Array.isArray(o.material) ? o.material[0] : o.material) as THREE.MeshStandardMaterial;
    });
    expect(live).not.toBeNull();
    expect(live!.color.getHexString()).toBe(originalColor.getHexString());
    scene.dispose();
  });

  it('isolateClass("IfcWall") hides non-wall meshes', async () => {
    const { FederatedViewerScene } = await import('../FederatedViewerScene');
    const scene = new FederatedViewerScene(mountCanvas());
    __setNextGLTF(makeMember(['IfcWall', 'IfcDoor', 'IfcWindow']));
    await scene.addMember({
      modelId: 'mod-a',
      discipline: 'arch',
      glbBuffer: new ArrayBuffer(8),
      originOffset: { x: 0, y: 0, z: 0 },
    });
    scene.isolateClass('IfcWall');
    expect(scene.getIsolatedClass()).toBe('IfcWall');

    const member = scene.getMemberGroup('mod-a')!;
    const visibilityByClass: Record<string, boolean> = {};
    member.traverse((o) => {
      if (o instanceof THREE.Mesh) {
        visibilityByClass[o.userData.ifcClass as string] = o.visible;
      }
    });
    expect(visibilityByClass.IfcWall).toBe(true);
    expect(visibilityByClass.IfcDoor).toBe(false);
    expect(visibilityByClass.IfcWindow).toBe(false);
    scene.dispose();
  });

  it('isolateClass(null) shows everything', async () => {
    const { FederatedViewerScene } = await import('../FederatedViewerScene');
    const scene = new FederatedViewerScene(mountCanvas());
    __setNextGLTF(makeMember(['IfcWall', 'IfcDoor']));
    await scene.addMember({
      modelId: 'mod-a',
      discipline: 'arch',
      glbBuffer: new ArrayBuffer(8),
      originOffset: { x: 0, y: 0, z: 0 },
    });
    scene.isolateClass('IfcWall');
    scene.isolateClass(null);
    expect(scene.getIsolatedClass()).toBeNull();
    const member = scene.getMemberGroup('mod-a')!;
    member.traverse((o) => {
      if (o instanceof THREE.Mesh) expect(o.visible).toBe(true);
    });
    scene.dispose();
  });

  it('setMemberVisible toggles the member Group', async () => {
    const { FederatedViewerScene } = await import('../FederatedViewerScene');
    const scene = new FederatedViewerScene(mountCanvas());
    __setNextGLTF(makeMember(['IfcWall']));
    await scene.addMember({
      modelId: 'mod-a',
      discipline: 'arch',
      glbBuffer: new ArrayBuffer(8),
      originOffset: { x: 0, y: 0, z: 0 },
    });
    const member = scene.getMemberGroup('mod-a')!;
    expect(member.visible).toBe(true);
    scene.setMemberVisible('mod-a', false);
    expect(member.visible).toBe(false);
    scene.setMemberVisible('mod-a', true);
    expect(member.visible).toBe(true);
    // No-op on unknown id - must NOT throw.
    expect(() => scene.setMemberVisible('does-not-exist', false)).not.toThrow();
    scene.dispose();
  });

  it('removeMember removes the Group and disposes geometry', async () => {
    const { FederatedViewerScene } = await import('../FederatedViewerScene');
    const scene = new FederatedViewerScene(mountCanvas());

    const root = new THREE.Group();
    const geom = new THREE.BoxGeometry(1, 1, 1);
    const disposeSpy = vi.spyOn(geom, 'dispose');
    const mat = new THREE.MeshStandardMaterial();
    const matDisposeSpy = vi.spyOn(mat, 'dispose');
    const mesh = new THREE.Mesh(geom, mat);
    mesh.name = 'IfcWall_001';
    root.add(mesh);
    __setNextGLTF(root);

    await scene.addMember({
      modelId: 'mod-a',
      discipline: 'arch',
      glbBuffer: new ArrayBuffer(8),
      originOffset: { x: 0, y: 0, z: 0 },
    });
    expect(scene.getMemberCount()).toBe(1);

    scene.removeMember('mod-a');
    expect(scene.getMemberCount()).toBe(0);
    expect(scene.getMemberGroup('mod-a')).toBeUndefined();
    expect(disposeSpy).toHaveBeenCalled();
    expect(matDisposeSpy).toHaveBeenCalled();
    scene.dispose();
  });

  it('dispose clears animation loop + disposes renderer + flips isDisposed()', async () => {
    const cancelSpy = vi.fn();
    vi.stubGlobal('cancelAnimationFrame', cancelSpy as unknown as typeof cancelAnimationFrame);
    vi.stubGlobal(
      'requestAnimationFrame',
      ((cb: FrameRequestCallback) => {
        // Return a non-zero token so dispose actually calls cancelAnimationFrame.
        void cb;
        return 42;
      }) as unknown as typeof requestAnimationFrame,
    );

    const { FederatedViewerScene } = await import('../FederatedViewerScene');
    const scene = new FederatedViewerScene(mountCanvas());
    const rendererDispose = vi.spyOn(scene.renderer, 'dispose');
    const controlsDispose = vi.spyOn(scene.controls, 'dispose');

    expect(scene.isDisposed()).toBe(false);
    scene.dispose();
    expect(scene.isDisposed()).toBe(true);
    expect(cancelSpy).toHaveBeenCalledWith(42);
    expect(rendererDispose).toHaveBeenCalled();
    expect(controlsDispose).toHaveBeenCalled();

    // Double-dispose is a no-op.
    expect(() => scene.dispose()).not.toThrow();
  });

  it('addMember on an existing modelId replaces the previous member', async () => {
    const { FederatedViewerScene } = await import('../FederatedViewerScene');
    const scene = new FederatedViewerScene(mountCanvas());

    __setNextGLTF(makeMember(['IfcWall']));
    await scene.addMember({
      modelId: 'mod-a',
      discipline: 'arch',
      glbBuffer: new ArrayBuffer(8),
      originOffset: { x: 0, y: 0, z: 0 },
    });
    const first = scene.getMemberGroup('mod-a');

    __setNextGLTF(makeMember(['IfcDoor']));
    await scene.addMember({
      modelId: 'mod-a',
      discipline: 'arch',
      glbBuffer: new ArrayBuffer(8),
      originOffset: { x: 0, y: 0, z: 0 },
    });
    const second = scene.getMemberGroup('mod-a');

    expect(scene.getMemberCount()).toBe(1);
    expect(second).not.toBe(first);
    scene.dispose();
  });
});
