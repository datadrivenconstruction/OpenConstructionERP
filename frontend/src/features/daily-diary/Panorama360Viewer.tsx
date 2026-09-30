// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Equirectangular 360-degree panorama viewer for stored ``is_360`` site
 * photos.
 *
 * Renders the photo as the texture on the INSIDE of a sphere (the classic
 * photo-sphere trick: a sphere scaled ``-1`` on X so its faces point inward,
 * camera at the centre). OrbitControls gives drag-to-look and scroll-to-zoom
 * (FOV-clamped so you can't turn the sphere inside-out); Escape or the close
 * button dismisses it.
 *
 * The three.js lifecycle (one renderer per mount, WebGL try/catch fallback,
 * ResizeObserver, full disposal on unmount) mirrors the point-cloud viewer so
 * the two stay consistent. The image is the already-served photo ``file_url``
 * - no new endpoint, no re-upload. That URL is usually a bearer-protected API
 * route, and ``TextureLoader`` requests it the way an ``<img>`` does, without
 * the token, so it is resolved through ``useAuthedObjectUrl`` first.
 */
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { AlertCircle, Loader2, RotateCcw, X } from 'lucide-react';
import { useAuthedObjectUrl } from '@/shared/ui/AuthImage';

type Phase = 'loading' | 'ready' | 'error';

/** Vertical field-of-view bounds (degrees). Scroll-to-zoom moves between
 * these; staying < 90deg keeps the viewer well inside the sphere. */
const FOV_MIN = 30;
const FOV_MAX = 90;
const FOV_START = 75;

export interface Panorama360ViewerProps {
  /** Full-resolution equirectangular image URL (the photo's ``file_url``). */
  imageUrl: string;
  /** Accessible caption / alt text, e.g. the photo description or location. */
  label?: string;
  onClose: () => void;
}

export function Panorama360Viewer({ imageUrl, label, onClose }: Panorama360ViewerProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const [phase, setPhase] = useState<Phase>('loading');
  const [webglFailed, setWebglFailed] = useState(false);
  const { url: textureUrl, failed: fetchFailed } = useAuthedObjectUrl(imageUrl);

  useEffect(() => {
    if (fetchFailed) setPhase('error');
  }, [fetchFailed]);

  // Close on Escape from anywhere while the overlay is open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // ── Scene lifecycle: one renderer per mount, disposed on unmount ──────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !textureUrl) return undefined;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      setWebglFailed(true);
      return undefined;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(container.clientWidth || 1, container.clientHeight || 1);
    renderer.domElement.style.display = 'block';
    container.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x000000);

    const camera = new THREE.PerspectiveCamera(
      FOV_START,
      (container.clientWidth || 1) / (container.clientHeight || 1),
      0.1,
      100,
    );
    // Sit at the centre of the sphere; OrbitControls rotates the view around
    // this point. A hair off-centre so the initial orientation is stable.
    camera.position.set(0, 0, 0.01);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    // Pan would move the camera out of the sphere centre and break the
    // illusion; zoom is remapped to FOV below instead of dollying.
    controls.enablePan = false;
    controls.enableZoom = false;
    controls.rotateSpeed = -0.3; // drag direction matches a photo-sphere
    controls.target.set(0, 0, 0);

    cameraRef.current = camera;
    controlsRef.current = controls;

    // Scroll / pinch -> change FOV (true panorama zoom) rather than dolly.
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const next = camera.fov + (e.deltaY > 0 ? 3 : -3);
      camera.fov = Math.min(FOV_MAX, Math.max(FOV_MIN, next));
      camera.updateProjectionMatrix();
    };
    renderer.domElement.addEventListener('wheel', onWheel, { passive: false });

    // Sphere with the equirectangular photo on the inside. scale.x = -1 flips
    // the geometry so its faces (and the texture) point inward at the camera.
    const geometry = new THREE.SphereGeometry(10, 64, 48);
    geometry.scale(-1, 1, 1);

    const loader = new THREE.TextureLoader();
    loader.setCrossOrigin('anonymous');
    let mesh: THREE.Mesh | null = null;
    let material: THREE.MeshBasicMaterial | null = null;
    let texture: THREE.Texture | null = null;
    let disposed = false;

    loader.load(
      textureUrl,
      (tex) => {
        if (disposed) {
          tex.dispose();
          return;
        }
        // srgb so the photo's colours are not washed out / over-bright.
        tex.colorSpace = THREE.SRGBColorSpace;
        texture = tex;
        material = new THREE.MeshBasicMaterial({ map: tex });
        mesh = new THREE.Mesh(geometry, material);
        scene.add(mesh);
        setPhase('ready');
      },
      undefined,
      () => {
        if (!disposed) setPhase('error');
      },
    );

    renderer.setAnimationLoop(() => {
      controls.update();
      renderer.render(scene, camera);
    });

    const observer = new ResizeObserver(() => {
      const w = container.clientWidth || 1;
      const h = container.clientHeight || 1;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    });
    observer.observe(container);

    return () => {
      disposed = true;
      observer.disconnect();
      renderer.setAnimationLoop(null);
      renderer.domElement.removeEventListener('wheel', onWheel);
      controls.dispose();
      if (mesh) scene.remove(mesh);
      geometry.dispose();
      material?.dispose();
      texture?.dispose();
      // Release the GL context slot before dispose() so the panorama viewer
      // does not leak a live WebGL context on unmount.
      try {
        renderer.forceContextLoss();
      } catch {
        /* context already lost */
      }
      renderer.dispose();
      if (renderer.domElement.parentElement === container) {
        container.removeChild(renderer.domElement);
      }
      cameraRef.current = null;
      controlsRef.current = null;
    };
  }, [textureUrl]);

  const handleReset = () => {
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!camera || !controls) return;
    camera.fov = FOV_START;
    camera.updateProjectionMatrix();
    controls.reset();
    controls.target.set(0, 0, 0);
    controls.update();
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex flex-col bg-black/95"
      role="dialog"
      aria-modal="true"
      aria-label={
        label
          ? t('daily_diary.panorama_aria_named', {
              defaultValue: '360-degree panorama viewer: {{name}}',
              name: label,
            })
          : t('daily_diary.panorama_aria', { defaultValue: '360-degree panorama viewer' })
      }
      data-testid="daily-diary-panorama-viewer"
    >
      {/* Top bar: title + controls. */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 text-white">
        <div className="flex min-w-0 items-center gap-2">
          <span className="inline-flex items-center rounded-md bg-white/15 px-2 py-0.5 text-xs font-semibold">
            {t('daily_diary.badge_360', { defaultValue: '360' })}
          </span>
          <span className="truncate text-sm font-medium">
            {label || t('daily_diary.panorama_title', { defaultValue: 'Panorama' })}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={handleReset}
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-white/90 transition-colors hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-white/40"
            title={t('daily_diary.panorama_reset', { defaultValue: 'Reset view' })}
            data-testid="daily-diary-panorama-reset"
          >
            <RotateCcw size={15} />
            <span className="hidden sm:inline">
              {t('daily_diary.panorama_reset', { defaultValue: 'Reset view' })}
            </span>
          </button>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-white/90 transition-colors hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-white/40"
            title={t('common.close', { defaultValue: 'Close' })}
            data-testid="daily-diary-panorama-close"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
            <span className="hidden sm:inline">
              {t('common.close', { defaultValue: 'Close' })}
            </span>
          </button>
        </div>
      </div>

      {/* Canvas + status overlays. */}
      <div
        ref={containerRef}
        className="relative flex-1 overflow-hidden"
        data-testid="daily-diary-panorama-canvas"
      >
        {webglFailed && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-6 text-center text-white">
            <AlertCircle size={22} className="text-red-400" />
            <p className="text-sm font-medium">
              {t('daily_diary.panorama_webgl_title', { defaultValue: '3D rendering unavailable' })}
            </p>
            <p className="max-w-md text-xs text-white/70">
              {t('daily_diary.panorama_webgl_desc', {
                defaultValue:
                  'WebGL could not start in this browser. Update your browser or enable hardware acceleration to view 360 photos.',
              })}
            </p>
          </div>
        )}

        {!webglFailed && phase === 'loading' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-white">
            <Loader2 size={22} className="animate-spin" />
            <p className="text-sm text-white/80">
              {t('daily_diary.panorama_loading', { defaultValue: 'Loading panorama...' })}
            </p>
          </div>
        )}

        {!webglFailed && phase === 'error' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-6 text-center text-white">
            <AlertCircle size={22} className="text-red-400" />
            <p className="text-sm font-medium">
              {t('daily_diary.panorama_error_title', { defaultValue: 'Could not load this photo' })}
            </p>
            <p className="max-w-md text-xs text-white/70">
              {t('daily_diary.panorama_error_desc', {
                defaultValue: 'The image could not be loaded. It may have been moved or removed.',
              })}
            </p>
          </div>
        )}
      </div>

      {!webglFailed && phase === 'ready' && (
        <p className="px-4 py-2 text-center text-2xs text-white/60">
          {t('daily_diary.panorama_hint', {
            defaultValue: 'Drag to look around, scroll to zoom, Esc to close.',
          })}
        </p>
      )}
    </div>
  );
}

export default Panorama360Viewer;
