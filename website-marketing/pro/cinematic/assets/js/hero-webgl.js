// ═══════════════════════════════════════════════════════════════════
// HERO WEBGL — architectural wireframe building, floating on grid
// Three.js scene with instanced building, particles, wireframe, fog.
// ═══════════════════════════════════════════════════════════════════

import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.161.0/build/three.module.js';

export function initHeroWebGL(canvas) {
  const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x0a0a0b, 0.024);

  // camera ——————————————————————————————
  const camera = new THREE.PerspectiveCamera(
    45,
    canvas.clientWidth / canvas.clientHeight,
    0.1,
    500,
  );
  camera.position.set(18, 14, 22);
  camera.lookAt(0, 4, 0);

  // renderer ——————————————————————————————
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    powerPreference: 'high-performance',
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
  renderer.setClearColor(0x000000, 0);

  // lights ——————————————————————————————
  const ambient = new THREE.AmbientLight(0x3f3f46, 0.6);
  scene.add(ambient);

  const keyLight = new THREE.DirectionalLight(0x3b82f6, 1.6);
  keyLight.position.set(12, 20, 10);
  scene.add(keyLight);

  const fillLight = new THREE.DirectionalLight(0x8b5cf6, 0.8);
  fillLight.position.set(-14, 10, -6);
  scene.add(fillLight);

  const rim = new THREE.DirectionalLight(0xec4899, 0.3);
  rim.position.set(0, -10, -20);
  scene.add(rim);

  // ground grid ——————————————————————————————
  const gridGroup = new THREE.Group();
  const gridSize = 100;
  const gridDiv = 50;
  const grid = new THREE.GridHelper(gridSize, gridDiv, 0x3b82f6, 0x1d1d22);
  grid.material.transparent = true;
  grid.material.opacity = 0.18;
  grid.position.y = 0;
  gridGroup.add(grid);

  // subtle inner grid
  const grid2 = new THREE.GridHelper(gridSize, gridDiv * 2, 0x222226, 0x222226);
  grid2.material.transparent = true;
  grid2.material.opacity = 0.08;
  grid2.position.y = -0.02;
  gridGroup.add(grid2);

  scene.add(gridGroup);

  // building — instanced boxes forming a tower —————————————————
  const buildingGroup = new THREE.Group();

  // procedural tower: a cluster of columns with varying heights
  const columns = [];
  const towerW = 6;
  const towerD = 6;
  const spacing = 1.1;
  const maxH = 14;

  function heightAt(x, z) {
    // radial falloff from center → stepped tower silhouette
    const cx = (towerW - 1) / 2;
    const cz = (towerD - 1) / 2;
    const dx = x - cx;
    const dz = z - cz;
    const dist = Math.sqrt(dx * dx + dz * dz);
    // layered heights
    const base = Math.max(1, maxH - dist * 2.4 - Math.random() * 1.5);
    return Math.max(1, Math.round(base));
  }

  for (let x = 0; x < towerW; x++) {
    for (let z = 0; z < towerD; z++) {
      const h = heightAt(x, z);
      columns.push({ x, z, h });
    }
  }

  // material for filled boxes
  const fillMat = new THREE.MeshStandardMaterial({
    color: 0x1a1a20,
    metalness: 0.35,
    roughness: 0.75,
    transparent: true,
    opacity: 0.88,
  });

  // material for wireframe edges
  const edgeMat = new THREE.LineBasicMaterial({
    color: 0x6b7aff,
    transparent: true,
    opacity: 0.75,
  });

  const floorHeight = 0.9;
  const floorGap = 0.08;

  columns.forEach(({ x, z, h }) => {
    const posX = (x - (towerW - 1) / 2) * spacing;
    const posZ = (z - (towerD - 1) / 2) * spacing;

    for (let i = 0; i < h; i++) {
      const boxGeo = new THREE.BoxGeometry(
        spacing * 0.92,
        floorHeight,
        spacing * 0.92,
      );
      const box = new THREE.Mesh(boxGeo, fillMat);
      box.position.set(posX, i * (floorHeight + floorGap) + floorHeight / 2, posZ);
      buildingGroup.add(box);

      const edges = new THREE.EdgesGeometry(boxGeo);
      const line = new THREE.LineSegments(edges, edgeMat);
      line.position.copy(box.position);
      buildingGroup.add(line);
    }
  });

  // highlight floors — occasional glowing floor on top of each column
  columns.forEach(({ x, z, h }) => {
    if (Math.random() > 0.65) {
      const posX = (x - (towerW - 1) / 2) * spacing;
      const posZ = (z - (towerD - 1) / 2) * spacing;
      const topY = (h - 1) * (floorHeight + floorGap) + floorHeight / 2;

      const glowGeo = new THREE.BoxGeometry(
        spacing * 0.94,
        floorHeight * 0.3,
        spacing * 0.94,
      );
      const glowMat = new THREE.MeshBasicMaterial({
        color: Math.random() > 0.5 ? 0x3b82f6 : 0x8b5cf6,
        transparent: true,
        opacity: 0.42,
      });
      const glow = new THREE.Mesh(glowGeo, glowMat);
      glow.position.set(posX, topY, posZ);
      glow.userData.baseOpacity = 0.42;
      glow.userData.phase = Math.random() * Math.PI * 2;
      buildingGroup.add(glow);
    }
  });

  scene.add(buildingGroup);

  // crane — a simple angular shape suggesting construction ————————
  const craneGroup = new THREE.Group();
  const craneMat = new THREE.LineBasicMaterial({
    color: 0xf59e0b,
    transparent: true,
    opacity: 0.55,
  });

  const pts = [];
  // vertical mast
  pts.push(new THREE.Vector3(-8, 0, -3));
  pts.push(new THREE.Vector3(-8, 16, -3));
  // horizontal jib
  pts.push(new THREE.Vector3(-8, 16, -3));
  pts.push(new THREE.Vector3(4, 17, -3));
  // counter-jib
  pts.push(new THREE.Vector3(-8, 16, -3));
  pts.push(new THREE.Vector3(-12, 15.5, -3));
  // cables
  pts.push(new THREE.Vector3(-2, 16.5, -3));
  pts.push(new THREE.Vector3(-2, 10, -3));
  pts.push(new THREE.Vector3(2, 16.8, -3));
  pts.push(new THREE.Vector3(2, 12, -3));

  const craneGeo = new THREE.BufferGeometry().setFromPoints(pts);
  const craneLines = new THREE.LineSegments(craneGeo, craneMat);
  craneGroup.add(craneLines);

  // crane hook
  const hookGeo = new THREE.BoxGeometry(0.5, 0.5, 0.5);
  const hookMat = new THREE.MeshBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.6 });
  const hook1 = new THREE.Mesh(hookGeo, hookMat);
  hook1.position.set(-2, 10, -3);
  const hook2 = new THREE.Mesh(hookGeo, hookMat);
  hook2.position.set(2, 12, -3);
  craneGroup.add(hook1);
  craneGroup.add(hook2);

  scene.add(craneGroup);

  // floating particles ——————————————————————————————
  const particlesGeo = new THREE.BufferGeometry();
  const particleCount = 280;
  const positions = new Float32Array(particleCount * 3);
  const velocities = new Float32Array(particleCount * 3);

  for (let i = 0; i < particleCount; i++) {
    positions[i * 3] = (Math.random() - 0.5) * 50;
    positions[i * 3 + 1] = Math.random() * 24;
    positions[i * 3 + 2] = (Math.random() - 0.5) * 50;

    velocities[i * 3] = (Math.random() - 0.5) * 0.008;
    velocities[i * 3 + 1] = (Math.random() - 0.2) * 0.008;
    velocities[i * 3 + 2] = (Math.random() - 0.5) * 0.008;
  }

  particlesGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));

  const particleTex = createSpriteTexture();
  const particlesMat = new THREE.PointsMaterial({
    color: 0x6b7aff,
    size: 0.12,
    transparent: true,
    opacity: 0.6,
    map: particleTex,
    alphaMap: particleTex,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });

  const particles = new THREE.Points(particlesGeo, particlesMat);
  scene.add(particles);

  // data points (BOQ style floating labels) — as bright dots —————————
  const dataPtsGeo = new THREE.BufferGeometry();
  const dataPts = new Float32Array([
    6, 8, 4,
    -6, 12, 3,
    4, 14, -4,
    8, 5, -2,
    -3, 3, 6,
    5, 10, 5,
  ]);
  dataPtsGeo.setAttribute('position', new THREE.BufferAttribute(dataPts, 3));
  const dataPtsMat = new THREE.PointsMaterial({
    color: 0x10b981,
    size: 0.35,
    transparent: true,
    opacity: 0.9,
    map: particleTex,
    alphaMap: particleTex,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  const dataPoints = new THREE.Points(dataPtsGeo, dataPtsMat);
  scene.add(dataPoints);

  // — scene tweaks — center & tilt ——————————————————————
  const sceneRoot = new THREE.Group();
  sceneRoot.add(buildingGroup);
  sceneRoot.add(craneGroup);
  scene.add(sceneRoot);

  // entrance animation — scale up buildings from ground ——————
  let entranceProgress = 0;
  const entranceDuration = 1800; // ms
  const entranceStart = performance.now();

  // camera parallax ——————————————————————————————
  const targetRot = { x: 0, y: 0 };
  const currentRot = { x: 0, y: 0 };
  let assembledPos = new Map();

  buildingGroup.children.forEach((child, i) => {
    assembledPos.set(child.uuid, child.position.clone());
    // initial: push below ground
    child.position.y -= 18 + (i % 20) * 0.2;
    child.userData.delay = (i % 30) / 30;
  });
  craneGroup.children.forEach((child) => {
    assembledPos.set(child.uuid, child.position.clone());
    child.position.y -= 20;
    child.userData.delay = 0.6;
  });

  function onMove(e) {
    if (prefersReduced) return;
    const rect = canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width - 0.5;
    const y = (e.clientY - rect.top) / rect.height - 0.5;
    targetRot.y = x * 0.22;
    targetRot.x = -y * 0.12;
  }
  window.addEventListener('pointermove', onMove, { passive: true });

  // on scroll — parallax camera up and zoom out slightly
  let scrollY = 0;
  function onScroll() {
    scrollY = window.scrollY;
  }
  window.addEventListener('scroll', onScroll, { passive: true });

  // resize ——————————————————————————————
  function resize() {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();

  // render loop ——————————————————————————————
  const clock = new THREE.Clock();
  let raf;
  function animate() {
    raf = requestAnimationFrame(animate);
    const t = clock.getElapsedTime();

    // entrance — ease buildings up
    const now = performance.now();
    if (entranceProgress < 1) {
      const raw = (now - entranceStart) / entranceDuration;
      entranceProgress = Math.min(raw, 1);

      buildingGroup.children.forEach((child) => {
        const target = assembledPos.get(child.uuid);
        if (!target) return;
        const delay = child.userData.delay ?? 0;
        const local = Math.min(1, Math.max(0, (entranceProgress - delay * 0.5) / (1 - delay * 0.5)));
        const eased = 1 - Math.pow(1 - local, 3);
        child.position.y = target.y + (1 - eased) * -18;
      });
      craneGroup.children.forEach((child) => {
        const target = assembledPos.get(child.uuid);
        if (!target) return;
        const delay = child.userData.delay ?? 0;
        const local = Math.min(1, Math.max(0, (entranceProgress - delay) / (1 - delay)));
        const eased = 1 - Math.pow(1 - local, 3);
        child.position.y = target.y + (1 - eased) * -20;
      });
    }

    // glow floor pulsing
    buildingGroup.children.forEach((child) => {
      if (child.userData.baseOpacity) {
        child.material.opacity =
          child.userData.baseOpacity * (0.65 + 0.35 * Math.sin(t * 1.5 + child.userData.phase));
      }
    });

    // particles drift
    const pos = particles.geometry.attributes.position.array;
    for (let i = 0; i < particleCount; i++) {
      pos[i * 3] += velocities[i * 3];
      pos[i * 3 + 1] += velocities[i * 3 + 1];
      pos[i * 3 + 2] += velocities[i * 3 + 2];
      // wrap
      if (pos[i * 3 + 1] > 24) pos[i * 3 + 1] = 0;
      if (pos[i * 3] > 25) pos[i * 3] = -25;
      if (pos[i * 3] < -25) pos[i * 3] = 25;
      if (pos[i * 3 + 2] > 25) pos[i * 3 + 2] = -25;
      if (pos[i * 3 + 2] < -25) pos[i * 3 + 2] = 25;
    }
    particles.geometry.attributes.position.needsUpdate = true;

    // data points pulse
    dataPointsMat.opacity = 0.6 + 0.3 * Math.sin(t * 2);

    // rotate scene gently
    if (!prefersReduced) {
      sceneRoot.rotation.y = t * 0.04 + currentRot.y;

      // camera parallax ease
      currentRot.x += (targetRot.x - currentRot.x) * 0.05;
      currentRot.y += (targetRot.y - currentRot.y) * 0.05;
    }

    // scroll parallax
    const scrollFactor = Math.min(1, scrollY / 900);
    camera.position.y = 14 + scrollFactor * 6;
    camera.position.z = 22 + scrollFactor * 8;
    camera.lookAt(0, 4 - scrollFactor * 2, 0);
    camera.rotation.z = currentRot.y * 0.05;

    renderer.render(scene, camera);
  }

  const dataPointsMat = dataPtsMat;

  animate();

  return {
    destroy() {
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('scroll', onScroll);
      renderer.dispose();
      scene.traverse((obj) => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
          if (Array.isArray(obj.material)) obj.material.forEach((m) => m.dispose());
          else obj.material.dispose();
        }
      });
    },
  };
}

// soft-circle sprite texture for particles
function createSpriteTexture() {
  const size = 64;
  const c = document.createElement('canvas');
  c.width = size; c.height = size;
  const ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, 'rgba(255,255,255,1)');
  g.addColorStop(0.4, 'rgba(255,255,255,0.6)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(c);
  tex.needsUpdate = true;
  return tex;
}
