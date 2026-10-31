"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";

/**
 * GridRestore login scene.
 * Matches the dark navy panel: deep blue backdrop, soft blue nodes, one amber vault,
 * and a muted coral for threats (no saturated red).
 * Composition is tighter: the dome frames the network and sits lower in the frame.
 * The threat-and-absorb moment reads as: a streak arrives, a bright impact flash
 * lands on the dome, and a ripple spreads across the surface.
 */

type NodeKind = "sub" | "critical" | "bus" | "load";
type GridNode = { id: string; x: number; y: number; z: number; kind: NodeKind };
type EdgeKind = "hub" | "ring" | "feed" | "perimeter";
type EdgeSpec = { a: string; b: string; kind: EdgeKind };

/* ---------- Layout ---------- */
const INNER_RADIUS = 2.65;
const OUTER_RADIUS = 5.25;
const GROUND_Y = -1.9;
const DOME_R = 6.0;
const DOME_DETAIL = 3;
const INNER_HEIGHTS = [0.32, 0.18, 0.4, 0.22, 0.36, 0.2];

/* ---------- Behaviour ---------- */
const PACKETS = 180;
const TRAIL = 3;
const THREATS = 5;
const THREAT_TRAIL = 8;
const MAX_IMPACTS = 6;
const FLASHES = 6;

/* ---------- Palette (sampled from the login panel) ---------- */
const BG_TOP = "#060d1a";
const BG_MID = "#030813";
const BG_BOTTOM = "#01040a";
const FOG = 0x030813;
const LINE = new THREE.Color(0x3a78b8);
const DOME_COLOR = new THREE.Color(0x7cc0ff);
const NODE_SUB = new THREE.Color(0xcfe9ff);
const NODE_BUS = new THREE.Color(0x58b4f0);
const NODE_LOAD = new THREE.Color(0x4f86c4);
const VAULT = new THREE.Color(0xf5b942);
const PACKET_A = new THREE.Color(0xd9edff);
const PACKET_B = new THREE.Color(0x66b8ff);
const THREAT = new THREE.Color(0xf2a58a); // muted coral, easy on the eyes
const THREAT_HOT = new THREE.Color(0xffd2bf);

const NODE_SIZE: Record<NodeKind, number> = { sub: 0.11, critical: 0.085, bus: 0.065, load: 0.045 };
const HALO_SIZE: Record<NodeKind, number> = { sub: 1.2, critical: 0.9, bus: 0.45, load: 0.32 };
const HALO_OPACITY: Record<NodeKind, number> = { sub: 0.3, critical: 0.3, bus: 0.14, load: 0.1 };
const EDGE_OPACITY: Record<EdgeKind, number> = { hub: 0.42, ring: 0.34, feed: 0.22, perimeter: 0.26 };

/* ---------- Network ---------- */

function buildNodes(): GridNode[] {
  const nodes: GridNode[] = [{ id: "S1", x: 0, y: 0.75, z: 0, kind: "sub" }];
  for (let i = 0; i < 6; i += 1) {
    const angle = (Math.PI / 3) * i;
    nodes.push({
      id: `B${i + 1}`,
      x: Math.cos(angle) * INNER_RADIUS,
      y: INNER_HEIGHTS[i],
      z: Math.sin(angle) * INNER_RADIUS,
      kind: i === 2 ? "critical" : "bus",
    });
  }
  for (let i = 0; i < 12; i += 1) {
    const angle = Math.PI / 12 + (Math.PI / 6) * i;
    nodes.push({
      id: `L${i + 1}`,
      x: Math.cos(angle) * OUTER_RADIUS,
      y: 0.06 + (i % 4) * 0.07,
      z: Math.sin(angle) * OUTER_RADIUS,
      kind: "load",
    });
  }
  return nodes;
}

function buildEdges(): EdgeSpec[] {
  const edges: EdgeSpec[] = [];
  for (let i = 0; i < 6; i += 1) edges.push({ a: "S1", b: `B${i + 1}`, kind: "hub" });
  for (let i = 0; i < 6; i += 1) edges.push({ a: `B${i + 1}`, b: `B${((i + 1) % 6) + 1}`, kind: "ring" });
  for (let i = 0; i < 12; i += 1) {
    const j = Math.floor(i / 2) % 6;
    edges.push({ a: `B${j + 1}`, b: `L${i + 1}`, kind: "feed" });
    edges.push({ a: `B${((j + 1) % 6) + 1}`, b: `L${i + 1}`, kind: "feed" });
  }
  for (let i = 0; i < 12; i += 1) edges.push({ a: `L${i + 1}`, b: `L${((i + 1) % 12) + 1}`, kind: "perimeter" });
  return edges;
}

const NODES = buildNodes();
const EDGES = buildEdges();
const NODE_INDEX = new Map(NODES.map((n, i) => [n.id, i]));

/* ---------- Helpers ---------- */

function makeSoftTexture(solid: number) {
  const canvas = document.createElement("canvas");
  canvas.width = 64;
  canvas.height = 64;
  const ctx = canvas.getContext("2d");
  if (!ctx) return new THREE.Texture();
  const g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(solid, "rgba(255,255,255,1)");
  g.addColorStop(Math.min(1, solid + 0.16), "rgba(255,255,255,0)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 64, 64);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/** Vertical gradient plus a soft light pool behind the dome, so the backdrop has depth without a grid. */
function makeBackdrop() {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 512;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  const g = ctx.createLinearGradient(0, 0, 0, 512);
  g.addColorStop(0, BG_TOP);
  g.addColorStop(0.55, BG_MID);
  g.addColorStop(1, BG_BOTTOM);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 512, 512);
  const pool = ctx.createRadialGradient(256, 300, 0, 256, 300, 260);
  pool.addColorStop(0, "rgba(40,90,160,0.14)");
  pool.addColorStop(1, "rgba(40,90,160,0)");
  ctx.fillStyle = pool;
  ctx.fillRect(0, 0, 512, 512);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/** Edges of a subdivided icosahedron, upper hemisphere only. */
function buildDomeEdges(radius: number, detail: number) {
  const ico = new THREE.IcosahedronGeometry(1, detail);
  const p = ico.attributes.position;
  const seen = new Set<string>();
  const out: number[] = [];
  const v = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()];
  const key = (a: THREE.Vector3) => `${a.x.toFixed(4)},${a.y.toFixed(4)},${a.z.toFixed(4)}`;
  for (let i = 0; i < p.count; i += 3) {
    v[0].fromBufferAttribute(p, i);
    v[1].fromBufferAttribute(p, i + 1);
    v[2].fromBufferAttribute(p, i + 2);
    for (let e = 0; e < 3; e += 1) {
      const a = v[e];
      const b = v[(e + 1) % 3];
      if (a.y < -0.001 || b.y < -0.001) continue;
      const ka = key(a);
      const kb = key(b);
      const k = ka < kb ? `${ka}|${kb}` : `${kb}|${ka}`;
      if (seen.has(k)) continue;
      seen.add(k);
      out.push(a.x * radius, a.y * radius, a.z * radius, b.x * radius, b.y * radius, b.z * radius);
    }
  }
  ico.dispose();
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(out), 3));
  return geometry;
}

/* ---------- Dome shaders ---------- */

const IMPACT_GLSL = /* glsl */ `
  uniform vec4 uImpacts[${MAX_IMPACTS}];
  uniform vec3 uHot;
  uniform vec3 uCoral;
  // Returns a 0..1 strength for an impact ripple at this surface point.
  float rippleAt(vec3 n, float age, vec3 dir) {
    if (age > 3.2) return 0.0;
    float d = acos(clamp(dot(n, dir), -1.0, 1.0));
    float r = age * 0.95;
    float ring = exp(-pow((d - r) * 16.0, 2.0)) * (1.0 - age / 3.2);
    float core = exp(-d * d * 60.0) * exp(-age * 3.5);
    return ring * 0.9 + core;
  }
  float impactAt(vec3 n) {
    float hit = 0.0;
    for (int i = 0; i < ${MAX_IMPACTS}; i++) {
      hit += rippleAt(n, uImpacts[i].w, uImpacts[i].xyz);
    }
    return clamp(hit, 0.0, 1.0);
  }
`;

const lineVertex = /* glsl */ `
  varying vec3 vObj;
  void main() {
    vObj = position;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const lineFragment = /* glsl */ `
  uniform float uTime;
  uniform vec3 uColor;
  uniform float uOpacity;
  varying vec3 vObj;
  ${IMPACT_GLSL}
  void main() {
    vec3 n = normalize(vObj);
    float fade = smoothstep(0.0, 0.18, n.y);
    float base = uOpacity * fade;
    float band = exp(-pow((n.y - fract(uTime / 12.0)) * 9.0, 2.0));
    base += 0.18 * band * fade;
    float hit = impactAt(n) * smoothstep(0.0, 0.15, n.y);
    vec3 col = mix(uColor, uHot, hit * 0.7);
    gl_FragColor = vec4(col, clamp(base + hit * 0.8, 0.0, 1.0));
  }
`;

const fillVertex = /* glsl */ `
  varying vec3 vObj;
  varying vec3 vNormalV;
  varying vec3 vViewPos;
  void main() {
    vObj = position;
    vNormalV = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vViewPos = mv.xyz;
    gl_Position = projectionMatrix * mv;
  }
`;

const fillFragment = /* glsl */ `
  uniform vec3 uColor;
  varying vec3 vObj;
  varying vec3 vNormalV;
  varying vec3 vViewPos;
  ${IMPACT_GLSL}
  void main() {
    vec3 n = normalize(vObj);
    float fade = smoothstep(0.02, 0.5, n.y);
    float rim = pow(1.0 - abs(dot(normalize(vNormalV), normalize(-vViewPos))), 2.4);
    float hit = impactAt(n) * smoothstep(0.0, 0.15, n.y);
    vec3 col = mix(uColor, uCoral, hit * 0.5);
    gl_FragColor = vec4(col, (rim * 0.22 + 0.03) * fade + hit * 0.16);
  }
`;

/* ---------- Component ---------- */

export default function GridScene() {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = host.current;
    if (!container) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
    } catch {
      container.style.background = BG_BOTTOM;
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.domElement.style.display = "block";
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    container.appendChild(renderer.domElement);

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(FOG, 16, 34);
    const backdrop = makeBackdrop();
    if (backdrop) scene.background = backdrop;
    else renderer.setClearColor(BG_BOTTOM, 1);

    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 120);
    const root = new THREE.Group();
    scene.add(root);

    const haloTexture = makeSoftTexture(0.0);
    const dotTexture = makeSoftTexture(0.5);
    const positions = NODES.map((n) => new THREE.Vector3(n.x, n.y, n.z));
    const additive = { transparent: true, blending: THREE.AdditiveBlending, depthWrite: false } as const;

    /* ---------- Dome (lives in its own group so threats can share its space) ---------- */
    const dome = new THREE.Group();
    dome.position.y = GROUND_Y;
    root.add(dome);

    const impacts = Array.from({ length: MAX_IMPACTS }, () => new THREE.Vector4(0, 1, 0, 99));
    const domeUniforms = {
      uTime: { value: 0 },
      uColor: { value: DOME_COLOR },
      uOpacity: { value: 0.75 },
      uHot: { value: THREAT_HOT },
      uCoral: { value: THREAT },
      uImpacts: { value: impacts },
    };
    const domeLines = new THREE.LineSegments(
      buildDomeEdges(DOME_R, DOME_DETAIL),
      new THREE.ShaderMaterial({
        uniforms: domeUniforms,
        vertexShader: lineVertex,
        fragmentShader: lineFragment,
        transparent: true,
        depthWrite: false,
      }),
    );
    dome.add(domeLines);

    const domeFill = new THREE.Mesh(
      new THREE.SphereGeometry(DOME_R * 0.998, 72, 28, 0, Math.PI * 2, 0, Math.PI / 2),
      new THREE.ShaderMaterial({
        uniforms: domeUniforms,
        vertexShader: fillVertex,
        fragmentShader: fillFragment,
        transparent: true,
        depthWrite: false,
        side: THREE.DoubleSide,
      }),
    );
    dome.add(domeFill);

    // Base ring where the dome meets the ground.
    const baseRing = new THREE.LineLoop(
      new THREE.BufferGeometry().setFromPoints(
        Array.from({ length: 180 }, (_, i) => {
          const a = (Math.PI * 2 * i) / 180;
          return new THREE.Vector3(Math.cos(a) * DOME_R, 0, Math.sin(a) * DOME_R);
        }),
      ),
      new THREE.LineBasicMaterial({ color: DOME_COLOR, transparent: true, opacity: 0.6, depthWrite: false }),
    );
    dome.add(baseRing);

    /* ---------- Edges ---------- */
    type EdgeRuntime = { spec: EdgeSpec; a: number; b: number; curve: THREE.QuadraticBezierCurve3 };
    const edges: EdgeRuntime[] = [];
    for (const spec of EDGES) {
      const a = NODE_INDEX.get(spec.a)!;
      const b = NODE_INDEX.get(spec.b)!;
      const pa = positions[a];
      const pb = positions[b];
      const mid = pa.clone().add(pb).multiplyScalar(0.5);
      if (spec.kind === "ring" || spec.kind === "perimeter") {
        const out = new THREE.Vector3(mid.x, 0, mid.z);
        if (out.lengthSq() > 0.001) out.normalize().multiplyScalar(0.26);
        mid.add(out);
        mid.y += 0.1;
      } else {
        mid.y += 0.5 + pa.distanceTo(pb) * 0.035;
      }
      const curve = new THREE.QuadraticBezierCurve3(pa, mid, pb);
      const touchesVault = spec.a === "B3" || spec.b === "B3";
      const color = touchesVault ? LINE.clone().lerp(VAULT, 0.35) : LINE;
      root.add(
        new THREE.Line(
          new THREE.BufferGeometry().setFromPoints(curve.getPoints(32)),
          new THREE.LineBasicMaterial({ color, transparent: true, opacity: EDGE_OPACITY[spec.kind], depthWrite: false }),
        ),
      );
      edges.push({ spec, a, b, curve });
    }

    type Hop = { edge: number; dir: 1 | -1 };
    const adjacency: Hop[][] = NODES.map(() => []);
    edges.forEach((e, i) => {
      adjacency[e.a].push({ edge: i, dir: 1 });
      adjacency[e.b].push({ edge: i, dir: -1 });
    });

    /* ---------- Nodes ---------- */
    const coreGeometry = new THREE.SphereGeometry(1, 16, 16);
    const nodeActivity = new Float32Array(NODES.length);
    const nodeViews = NODES.map((node, index) => {
      const color = node.kind === "sub" ? NODE_SUB : node.kind === "critical" ? VAULT : node.kind === "bus" ? NODE_BUS : NODE_LOAD;
      const core = new THREE.Mesh(coreGeometry, new THREE.MeshBasicMaterial({ color: color.clone() }));
      core.position.copy(positions[index]);
      core.scale.setScalar(NODE_SIZE[node.kind]);
      root.add(core);

      const halo = new THREE.Sprite(
        new THREE.SpriteMaterial({ map: haloTexture, color: color.clone(), opacity: HALO_OPACITY[node.kind], ...additive }),
      );
      halo.position.copy(positions[index]);
      halo.scale.setScalar(HALO_SIZE[node.kind]);
      root.add(halo);
      return { halo, kind: node.kind, color };
    });

    // Drop lines fade toward the ground.
    const dropPositions: number[] = [];
    const dropColors: number[] = [];
    for (const n of NODES) {
      if (n.kind === "bus") continue;
      const c = n.kind === "sub" ? NODE_SUB : n.kind === "critical" ? VAULT : NODE_LOAD;
      const k = n.kind === "load" ? 0.45 : 0.6;
      dropPositions.push(n.x, n.y, n.z, n.x, GROUND_Y, n.z);
      dropColors.push(c.r * k, c.g * k, c.b * k, 0, 0, 0);
    }
    const dropGeometry = new THREE.BufferGeometry();
    dropGeometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(dropPositions), 3));
    dropGeometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(dropColors), 3));
    root.add(new THREE.LineSegments(dropGeometry, new THREE.LineBasicMaterial({ vertexColors: true, ...additive })));

    /* ---------- Traffic ---------- */
    type Packet = { edge: number; dir: 1 | -1; t: number; speed: number; color: THREE.Color };
    const randomHop = (node: number, avoidEdge: number): Hop => {
      const options = adjacency[node];
      const forward = options.filter((h) => h.edge !== avoidEdge);
      const pool = forward.length ? forward : options;
      return pool[Math.floor(Math.random() * pool.length)];
    };
    const packets: Packet[] = Array.from({ length: PACKETS }, () => ({
      edge: Math.floor(Math.random() * edges.length),
      dir: Math.random() < 0.5 ? 1 : -1,
      t: Math.random(),
      speed: 0.9 + Math.random() * 1.4,
      color: Math.random() < 0.75 ? PACKET_A : PACKET_B,
    }));
    const packetPositions = new Float32Array(PACKETS * TRAIL * 3);
    const packetColors = new Float32Array(PACKETS * TRAIL * 3);
    const packetGeometry = new THREE.BufferGeometry();
    packetGeometry.setAttribute("position", new THREE.BufferAttribute(packetPositions, 3).setUsage(THREE.DynamicDrawUsage));
    packetGeometry.setAttribute("color", new THREE.BufferAttribute(packetColors, 3).setUsage(THREE.DynamicDrawUsage));
    const packetPoints = new THREE.Points(
      packetGeometry,
      new THREE.PointsMaterial({ size: 0.07, map: dotTexture, vertexColors: true, opacity: 0.95, sizeAttenuation: true, ...additive }),
    );
    packetPoints.frustumCulled = false;
    root.add(packetPoints);

    /* ---------- Threats: arrive over the dome, strike it, ripple out ---------- */
    type Threat = { active: boolean; start: THREE.Vector3; end: THREE.Vector3; dir: THREE.Vector3; t: number; speed: number };
    const threats: Threat[] = Array.from({ length: THREATS }, () => ({
      active: false,
      start: new THREE.Vector3(),
      end: new THREE.Vector3(),
      dir: new THREE.Vector3(),
      t: 0,
      speed: 1,
    }));
    const threatPositions = new Float32Array(THREATS * THREAT_TRAIL * 3);
    const threatColors = new Float32Array(THREATS * THREAT_TRAIL * 3);
    const threatGeometry = new THREE.BufferGeometry();
    threatGeometry.setAttribute("position", new THREE.BufferAttribute(threatPositions, 3).setUsage(THREE.DynamicDrawUsage));
    threatGeometry.setAttribute("color", new THREE.BufferAttribute(threatColors, 3).setUsage(THREE.DynamicDrawUsage));
    const threatPoints = new THREE.Points(
      threatGeometry,
      new THREE.PointsMaterial({ size: 0.12, map: dotTexture, vertexColors: true, opacity: 1, sizeAttenuation: true, ...additive }),
    );
    threatPoints.frustumCulled = false;
    dome.add(threatPoints);

    // Impact flashes: one sprite per recent strike, drawn at the contact point.
    const flashes = Array.from({ length: FLASHES }, () => {
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: haloTexture, color: THREAT_HOT.clone(), opacity: 0, ...additive }));
      dome.add(sprite);
      return { sprite, born: -99 };
    });
    let nextImpact = 0;
    let nextFlash = 0;
    let threatTimer = 1.2;
    const up = new THREE.Vector3(0, 1, 0);
    const tangent = new THREE.Vector3();

    const spawnThreat = () => {
      const slot = threats.find((t) => !t.active);
      if (!slot) return;
      // Approach from above the horizon, between two and four o'clock in the scene's frame.
      const azimuth = Math.random() * Math.PI * 2;
      const elevation = 0.5 + Math.random() * 0.6;
      slot.dir.set(Math.cos(elevation) * Math.cos(azimuth), Math.sin(elevation), Math.cos(elevation) * Math.sin(azimuth));
      slot.end.copy(slot.dir).multiplyScalar(DOME_R);
      tangent.crossVectors(slot.dir, up).normalize();
      slot.start
        .copy(slot.dir)
        .multiplyScalar(DOME_R + 4.5)
        .addScaledVector(tangent, (Math.random() - 0.5) * 3);
      slot.t = 0;
      slot.speed = 0.85 + Math.random() * 0.45;
      slot.active = true;
    };

    const strike = (th: Threat) => {
      const imp = impacts[nextImpact++ % MAX_IMPACTS];
      imp.set(th.dir.x, th.dir.y, th.dir.z, 0);
      const f = flashes[nextFlash++ % FLASHES];
      f.sprite.position.copy(th.end);
      f.born = clockNow;
    };

    let clockNow = 0;

    /* ---------- Pointer + resize ---------- */
    const pointer = { x: 0, y: 0 };
    const drift = { x: 0, y: 0 };
    const onPointerMove = (e: PointerEvent) => {
      pointer.x = (e.clientX / window.innerWidth - 0.5) * 2;
      pointer.y = (e.clientY / window.innerHeight - 0.5) * 2;
    };
    const onPointerDown = (e: PointerEvent) => {
      if ((e.target as HTMLElement | null)?.closest?.("input,button,a,textarea,select,label")) return;
      spawnThreat();
    };
    if (!reduceMotion) {
      window.addEventListener("pointermove", onPointerMove, { passive: true });
      window.addEventListener("pointerdown", onPointerDown, { passive: true });
    }

    let baseY = 6;
    let baseZ = 14;
    const resize = () => {
      const w = container.clientWidth;
      const h = container.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      const fit = Math.max(0.7, Math.min(1.25, camera.aspect));
      const distance = 16.5 / fit;
      baseY = distance * 0.34;
      baseZ = distance * 0.95;
      camera.position.set(0, baseY, baseZ);
      camera.lookAt(0, 0.4, 0);
      camera.updateProjectionMatrix();
      renderer.render(scene, camera);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    resize();

    /* ---------- Frame update ---------- */
    const tmp = new THREE.Vector3();
    const tmpCol = new THREE.Color();
    const curveParam = (dir: 1 | -1, t: number) => (dir > 0 ? t : 1 - t);

    const update = (elapsed: number, delta: number) => {
      clockNow = elapsed;
      domeUniforms.uTime.value = elapsed;
      const dAct = Math.exp(-delta * 3);
      for (let i = 0; i < NODES.length; i += 1) nodeActivity[i] *= dAct;
      impacts.forEach((imp) => {
        if (imp.w < 50) imp.w += delta;
      });

      // Traffic
      for (let i = 0; i < PACKETS; i += 1) {
        const p = packets[i];
        p.t += p.speed * delta;
        if (p.t >= 1) {
          const e = edges[p.edge];
          const node = p.dir > 0 ? e.b : e.a;
          nodeActivity[node] = Math.min(1, nodeActivity[node] + 0.3);
          const hop = randomHop(node, p.edge);
          p.edge = hop.edge;
          p.dir = hop.dir;
          p.t -= 1;
        }
        const curve = edges[p.edge].curve;
        for (let k = 0; k < TRAIL; k += 1) {
          curve.getPoint(curveParam(p.dir, Math.max(0, p.t - k * 0.05)), tmp);
          const idx = (i * TRAIL + k) * 3;
          packetPositions[idx] = tmp.x;
          packetPositions[idx + 1] = tmp.y;
          packetPositions[idx + 2] = tmp.z;
          tmpCol.copy(p.color).multiplyScalar(1 - k * 0.4);
          tmpCol.toArray(packetColors, idx);
        }
      }
      packetGeometry.attributes.position.needsUpdate = true;
      packetGeometry.attributes.color.needsUpdate = true;

      // Threats
      threatTimer -= delta;
      if (threatTimer <= 0 && delta > 0) {
        spawnThreat();
        threatTimer = 1.1 + Math.random() * 1.3;
      }
      threats.forEach((th, i) => {
        if (th.active) {
          th.t += th.speed * delta;
          if (th.t >= 1) {
            th.active = false;
            strike(th);
          }
        }
        for (let k = 0; k < THREAT_TRAIL; k += 1) {
          const idx = (i * THREAT_TRAIL + k) * 3;
          if (!th.active) {
            threatColors[idx] = threatColors[idx + 1] = threatColors[idx + 2] = 0;
            continue;
          }
          const s = Math.max(0, th.t - k * 0.03);
          tmp.lerpVectors(th.start, th.end, s);
          threatPositions[idx] = tmp.x;
          threatPositions[idx + 1] = tmp.y;
          threatPositions[idx + 2] = tmp.z;
          // Head is hot, tail fades into the navy background.
          tmpCol.copy(THREAT_HOT).lerp(THREAT, k / THREAT_TRAIL).multiplyScalar(Math.pow(1 - k / THREAT_TRAIL, 1.4));
          tmpCol.toArray(threatColors, idx);
        }
      });
      threatGeometry.attributes.position.needsUpdate = true;
      threatGeometry.attributes.color.needsUpdate = true;

      // Impact flashes: quick bloom that settles into a soft glow.
      flashes.forEach((f) => {
        const k = (elapsed - f.born) / 0.9;
        const mat = f.sprite.material as THREE.SpriteMaterial;
        if (k < 0 || k > 1) {
          mat.opacity = 0;
          return;
        }
        f.sprite.scale.setScalar(0.25 + Math.sqrt(k) * 1.4);
        mat.opacity = (1 - k) * (1 - k) * 0.85;
      });

      // Nodes react to traffic
      nodeViews.forEach((v, i) => {
        const act = nodeActivity[i];
        const mat = v.halo.material as THREE.SpriteMaterial;
        mat.opacity = HALO_OPACITY[v.kind] + act * 0.16;
        v.halo.scale.setScalar(HALO_SIZE[v.kind] * (1 + act * 0.25));
      });
    };

    /* ---------- Loop ---------- */
    let frame = 0;
    let t0 = 0;
    let last = 0;
    const animate = (now: number) => {
      if (!t0) t0 = now;
      const elapsed = (now - t0) / 1000;
      const delta = last ? Math.min(0.05, (now - last) / 1000) : 0;
      last = now;

      update(elapsed, delta);

      drift.x += (pointer.x * 0.45 - drift.x) * 0.03;
      drift.y += (-pointer.y * 0.2 - drift.y) * 0.03;
      camera.position.set(
        Math.sin(elapsed * 0.06) * 0.5 + drift.x,
        baseY + Math.sin(elapsed * 0.1) * 0.1 + drift.y,
        baseZ,
      );
      camera.lookAt(0, 0.4, 0);
      root.rotation.y += delta * 0.018;

      renderer.render(scene, camera);
      frame = requestAnimationFrame(animate);
    };

    if (reduceMotion) {
      update(0, 0);
      renderer.render(scene, camera);
    } else {
      frame = requestAnimationFrame(animate);
    }

    const onVisibilityChange = () => {
      if (reduceMotion) return;
      if (document.hidden) {
        cancelAnimationFrame(frame);
        frame = 0;
      } else if (!frame) {
        last = 0;
        frame = requestAnimationFrame(animate);
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      scene.traverse((object) => {
        if (
          object instanceof THREE.Mesh ||
          object instanceof THREE.Line ||
          object instanceof THREE.Points ||
          object instanceof THREE.LineSegments ||
          object instanceof THREE.LineLoop
        ) {
          object.geometry?.dispose();
          const material = object.material;
          if (Array.isArray(material)) material.forEach((m) => m.dispose());
          else material?.dispose();
        }
        if (object instanceof THREE.Sprite) object.material.dispose();
      });
      haloTexture.dispose();
      dotTexture.dispose();
      backdrop?.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div ref={host} className="auth-scene-canvas" aria-hidden="true" />;
}