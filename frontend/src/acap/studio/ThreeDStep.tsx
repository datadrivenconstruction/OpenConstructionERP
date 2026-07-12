import { useCallback, useEffect, useRef, useState } from 'react';
import { getLatestLayout } from '@/acap/floorPlanApi';
import { ApiError } from '@/shared/lib/api';
import type { FloorPlan } from '@/acap/planTypes';
import { planToMeshes } from './planTo3d';

interface ThreeDStepProps {
  projectId: string;
}

export function ThreeDStep({ projectId }: ThreeDStepProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hasWebGl, setHasWebGl] = useState<boolean | null>(null);
  const [plan, setPlan] = useState<FloorPlan | null>(null);
  const [loadError, setLoadError] = useState<'none' | 'no-layout' | 'error'>('none');
  const [showLevel, setShowLevel] = useState(0);
  const [rebuildNonce, setRebuildNonce] = useState(0);
  const cleanupRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    let cancelled = false;
    getLatestLayout(projectId)
      .then((res) => {
        if (!cancelled) setPlan(res.plan);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err instanceof ApiError && err.status === 404 ? 'no-layout' : 'error');
      });
    return () => { cancelled = true; };
  }, [projectId]);

  useEffect(() => {
    if (!plan || !containerRef.current) return;

    const container = containerRef.current;

    let cancelled = false;
    let frameId = 0;
    let renderer: any = null;
    const meshes: any[] = [];

    Promise.all([
      import('three'),
      import('three/addons/controls/OrbitControls.js'),
    ]).then(([THREE, { OrbitControls }]) => {
      // Effect may have re-run (level switch / reset) or unmounted while the
      // dynamic import was in flight — bail so we never mount a 2nd canvas or
      // orphan a WebGL context.
      if (cancelled || !container) return;

      try {
        renderer = new THREE.WebGLRenderer({ antialias: true });
      } catch {
        setHasWebGl(false);
        return;
      }
      setHasWebGl(true);

      const { floors, walls } = planToMeshes(plan);

      renderer.setSize(container.clientWidth, 480);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      container.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0xf0efec);

      const camera = new THREE.PerspectiveCamera(45, container.clientWidth / 480, 0.1, 100);
      const kavlingW = plan.kavling.width_m;
      const kavlingH = plan.kavling.length_m;
      const maxDim = Math.max(kavlingW, kavlingH, 6);
      camera.position.set(maxDim * 1.2, maxDim * 0.6, maxDim * 1.2);
      camera.lookAt(kavlingW / 2, 0, kavlingH / 2);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.target.set(kavlingW / 2, 1.5, kavlingH / 2);
      controls.update();

      const hemi = new THREE.HemisphereLight(0xffffff, 0x444444, 0.8);
      scene.add(hemi);
      const dir = new THREE.DirectionalLight(0xffffff, 1);
      dir.position.set(kavlingW, 6, kavlingH);
      scene.add(dir);

      const grid = new THREE.GridHelper(Math.max(kavlingW, kavlingH) + 4, 10, 0xcccccc, 0xdddddd);
      grid.position.y = 0;
      scene.add(grid);

      for (const slab of floors) {
        if (showLevel !== 0 && Math.floor(slab.z / 3.0) + 1 !== showLevel) continue;
        const geo = new THREE.BoxGeometry(slab.w, 0.2, slab.l);
        const mat = new THREE.MeshLambertMaterial({ color: 0xd6d3cd });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(slab.x + slab.w / 2, slab.z + 0.1, slab.y + slab.l / 2);
        scene.add(mesh);
        meshes.push(mesh);
      }

      for (const wall of walls) {
        if (showLevel !== 0) {
          const wallLevel = Math.floor((wall.cz - 1.5) / 3.2) + 1;
          if (wallLevel !== showLevel) continue;
        }
        const geo = new THREE.BoxGeometry(wall.lenX, wall.height, wall.lenY);
        const mat = new THREE.MeshLambertMaterial({ color: 0xe8e6e1 });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(wall.cx, wall.cz, wall.cy);
        scene.add(mesh);
        meshes.push(mesh);
      }

      const animate = () => {
        frameId = requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);
      };
      animate();

      const handleResize = () => {
        if (!container) return;
        const w = container.clientWidth;
        renderer.setSize(w, 480);
        camera.aspect = w / 480;
        camera.updateProjectionMatrix();
      };
      window.addEventListener('resize', handleResize);

      cleanupRef.current = () => {
        if (frameId) cancelAnimationFrame(frameId);
        window.removeEventListener('resize', handleResize);
        controls.dispose();
        renderer.dispose();
        for (const m of meshes) {
          m.geometry.dispose();
          if (Array.isArray(m.material)) m.material.forEach((mt: any) => mt.dispose());
          else m.material.dispose();
        }
        if (container.contains(renderer.domElement)) {
          container.removeChild(renderer.domElement);
        }
      };
    });

    return () => {
      cancelled = true;
      if (frameId) cancelAnimationFrame(frameId);
      cleanupRef.current?.();
      cleanupRef.current = null;
    };
  }, [plan, showLevel, rebuildNonce]);

  const switchLevel = useCallback((lvl: number) => {
    setShowLevel(lvl);
  }, []);

  const resetCamera = useCallback(() => {
    // Bump the nonce → effect teardown + rebuild fires, re-framing the camera.
    setRebuildNonce((n) => n + 1);
  }, []);

  if (loadError === 'no-layout') {
    return (
      <div className="rounded-md border border-border bg-surface-secondary p-4 text-sm text-content-secondary">
        Selesaikan langkah Konfirmasi dulu, lalu simpan denah untuk melihat 3D.
      </div>
    );
  }

  if (loadError === 'error') {
    return <div className="p-6 text-sm text-semantic-error">Gagal memuat denah.</div>;
  }

  if (hasWebGl === false) {
    return <div className="p-6 text-sm text-content-secondary">3D tidak tersedia di browser ini.</div>;
  }

  const levelCount = plan?.jumlah_lantai ?? 1;

  return (
    <div className="flex flex-col gap-3">
      {levelCount > 1 && (
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => switchLevel(0)}
            className={`rounded-md px-3 py-1 text-xs font-medium ${showLevel === 0 ? 'bg-oe-blue text-white' : 'border border-border text-content-secondary'}`}
          >
            Semua lantai
          </button>
          {Array.from({ length: levelCount }, (_, i) => i + 1).map((l) => (
            <button
              key={l}
              type="button"
              onClick={() => switchLevel(l)}
              className={`rounded-md px-3 py-1 text-xs font-medium ${showLevel === l ? 'bg-oe-blue text-white' : 'border border-border text-content-secondary'}`}
            >
              Lantai {l}
            </button>
          ))}
        </div>
      )}
      <div ref={containerRef} className="h-[480px] w-full rounded-md border border-border" />
      <button
        type="button"
        onClick={resetCamera}
        className="self-start rounded-md border border-border px-3 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary"
      >
        Reset kamera
      </button>
    </div>
  );
}

export default ThreeDStep;
