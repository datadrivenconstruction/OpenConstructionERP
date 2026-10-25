/**
 * BIMViewCube tests — verifies face buttons are present and each one
 * calls SceneManager.setViewPreset() with the correct preset name (W6.6).
 *
 * WHY: We can't exercise the WebGL raycast in jsdom — three.js has no
 * GL context here. Instead we render the component, click the
 * accessible `sr-only` fallback buttons that mirror the cube faces,
 * and assert the public contract (`setViewPreset` dispatch).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';

/**
 * Lets a test decide whether the GL context can be had at all (#172). The
 * real failure is three.js throwing from inside the WebGLRenderer
 * constructor when the browser's per-page context budget is spent - the
 * viewer, the cube and any other 3-D widget all draw on the same allowance.
 */
const gl = vi.hoisted(() => ({ available: true }));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key,
    i18n: { language: 'en' },
  }),
}));

// Mock three.js WebGLRenderer + CanvasTexture so the component mounts
// in jsdom without crashing. We keep the real Scene / Camera / Box /
// Material classes — they're plain JS objects that don't need GL.
vi.mock('three', async () => {
  const actual = await vi.importActual<typeof import('three')>('three');
  class FakeWebGLRenderer {
    domElement: HTMLCanvasElement;
    constructor(opts: { canvas?: HTMLCanvasElement } = {}) {
      if (!gl.available) {
        // Shape of the real failure: three.js reads `.precision` off a null
        // getShaderPrecisionFormat result and raises a TypeError.
        throw new TypeError("Cannot read properties of null (reading 'precision')");
      }
      this.domElement =
        opts.canvas ?? (document.createElement('canvas') as HTMLCanvasElement);
    }
    setPixelRatio() {}
    setSize() {}
    setClearColor() {}
    render() {}
    forceContextLoss() {}
    dispose() {}
  }
  class FakeCanvasTexture {
    needsUpdate = true;
    constructor(_canvas?: HTMLCanvasElement) {
      void _canvas;
    }
    dispose() {}
  }
  return {
    ...actual,
    WebGLRenderer: FakeWebGLRenderer,
    CanvasTexture: FakeCanvasTexture,
  };
});

import { BIMViewCube } from '../BIMViewCube';
import type { SceneManager } from '../SceneManager';

function makeMockSceneManager(): {
  sm: SceneManager;
  setViewPreset: ReturnType<typeof vi.fn>;
  onCameraChange: ReturnType<typeof vi.fn>;
} {
  const setViewPreset = vi.fn().mockResolvedValue(undefined);
  const onCameraChange = vi.fn().mockReturnValue(() => {});
  const sm = {
    camera: { matrixWorld: { decompose: () => {} } },
    controls: { target: { copy: () => {} } },
    setViewPreset,
    onCameraChange,
  } as unknown as SceneManager;
  return { sm, setViewPreset, onCameraChange };
}

describe('BIMViewCube', () => {
  beforeEach(() => {
    gl.available = true;
  });

  afterEach(() => {
    cleanup();
  });

  it('renders the root widget with the expected test id', () => {
    const { sm } = makeMockSceneManager();
    render(<BIMViewCube sceneManager={sm} />);
    expect(screen.getByTestId('bim-view-cube')).toBeInTheDocument();
  });

  it('renders an accessible fallback button per face', () => {
    const { sm } = makeMockSceneManager();
    render(<BIMViewCube sceneManager={sm} />);
    for (const preset of ['top', 'bottom', 'front', 'back', 'left', 'right'] as const) {
      expect(screen.getByTestId(`bim-view-cube-face-${preset}`)).toBeInTheDocument();
    }
  });

  it('calls setViewPreset with the matching preset when a face button is clicked', () => {
    const { sm, setViewPreset } = makeMockSceneManager();
    render(<BIMViewCube sceneManager={sm} />);
    for (const preset of ['top', 'bottom', 'front', 'back', 'left', 'right'] as const) {
      screen.getByTestId(`bim-view-cube-face-${preset}`).click();
    }
    expect(setViewPreset).toHaveBeenCalledTimes(6);
    expect(setViewPreset.mock.calls.map((c) => c[0])).toEqual([
      'top',
      'bottom',
      'front',
      'back',
      'left',
      'right',
    ]);
  });

  it('subscribes to camera-change events on the active scene manager', () => {
    const { sm, onCameraChange } = makeMockSceneManager();
    render(<BIMViewCube sceneManager={sm} />);
    expect(onCameraChange).toHaveBeenCalled();
  });

  it('mounts safely when sceneManager is null', () => {
    expect(() =>
      render(<BIMViewCube sceneManager={null} />),
    ).not.toThrow();
    expect(screen.getByTestId('bim-view-cube')).toBeInTheDocument();
  });
});

/**
 * #172 - the widget mounts at size 112 pinned over the viewer
 * (BIMViewer.tsx:3401). When it cannot paint, it used to keep that 112x112
 * box in the layout with nothing drawn in it, which the browser renders as
 * an empty card with a broken graphic, sitting on top of the model.
 *
 * The report filed this against a model thumbnail in the filmstrip. It is
 * not one: BIMPage's ModelCard has no canvas and no img, which is also why
 * querySelectorAll('img') came back empty on the route and it took a
 * positional sweep to find. This is the only 112px canvas in the tree.
 */
describe('BIMViewCube when it cannot paint (#172)', () => {
  let warn: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
  });

  afterEach(() => {
    warn.mockRestore();
    gl.available = true;
    cleanup();
  });

  it('shows a placeholder when the renderer will not construct', () => {
    gl.available = false;
    render(<BIMViewCube sceneManager={null} size={112} />);

    const placeholder = screen.getByTestId('bim-view-cube-unavailable');
    // It has to name itself and say what happened. A bare grey box is the
    // same non-answer the blank canvas was.
    expect(placeholder.textContent).toMatch(/view cube/i);
    expect(placeholder.getAttribute('title')).toMatch(/3D graphics context/i);
  });

  it('takes the undrawn canvas out of the DOM instead of covering it', () => {
    // This is the assertion the fix turns on. A placeholder rendered NEXT to
    // a surviving canvas would leave the blank card exactly where it was and
    // add a caption beside it.
    gl.available = false;
    const { container } = render(<BIMViewCube sceneManager={null} size={112} />);

    expect(container.querySelector('canvas')).toBeNull();
  });

  it('keeps the orientation presets reachable', () => {
    // They call setViewPreset directly and need no GL of their own, so
    // losing the cube must not cost the user the ability to reorient.
    gl.available = false;
    const { sm, setViewPreset } = makeMockSceneManager();
    render(<BIMViewCube sceneManager={sm} size={112} />);

    screen.getByTestId('bim-view-cube-face-top').click();
    expect(setViewPreset).toHaveBeenCalledWith('top');
  });

  it('says something rather than failing silently', () => {
    gl.available = false;
    render(<BIMViewCube sceneManager={null} size={112} />);

    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining('[BIMViewCube]'),
      expect.anything(),
    );
  });

  it('swaps in the placeholder when the context is lost after a good start', () => {
    // The second failure path, and the one the report describes as ordinary
    // - a laptop switching GPUs, or waking from sleep. Here the renderer
    // constructs, so there is a real mounted canvas with the component's own
    // listener on it, and the event is dispatched at that canvas.
    //
    // What this does NOT do is lose an actual GL context; jsdom has none to
    // lose. It proves the component is listening on the right element and
    // reacts correctly. The browser-side check is DevTools:
    //   canvas.getContext('webgl').getExtension('WEBGL_lose_context').loseContext()
    const { sm } = makeMockSceneManager();
    const { container } = render(<BIMViewCube sceneManager={sm} size={112} />);

    const canvas = container.querySelector('canvas');
    expect(canvas).not.toBeNull();
    expect(screen.queryByTestId('bim-view-cube-unavailable')).toBeNull();

    act(() => {
      canvas!.dispatchEvent(new Event('webglcontextlost'));
    });

    expect(screen.getByTestId('bim-view-cube-unavailable')).toBeInTheDocument();
    expect(container.querySelector('canvas')).toBeNull();
  });
});

describe('BIMViewCube canvas lifecycle', () => {
  afterEach(() => cleanup());

  it('uses a fresh canvas for each effect run and leaves exactly one mounted (StrictMode)', async () => {
    const { StrictMode } = await import('react');
    const seen: Element[] = [];
    const original = document.createElement.bind(document);
    const spy = vi.spyOn(document, 'createElement').mockImplementation(((tag: string, o?: ElementCreationOptions) => {
      const el = original(tag, o);
      if (tag === 'canvas') seen.push(el);
      return el;
    }) as typeof document.createElement);
    const { container } = render(
      <StrictMode>
        <BIMViewCube sceneManager={null} size={80} />
      </StrictMode>,
    );
    spy.mockRestore();
    const viewCanvases = seen.filter((c) => (c as HTMLCanvasElement).width === 80);
    expect(viewCanvases.length).toBeGreaterThanOrEqual(2);
    expect(container.querySelectorAll('canvas')).toHaveLength(1);
    expect(container.querySelector('canvas')).toBe(viewCanvases[viewCanvases.length - 1]);
  });
});
