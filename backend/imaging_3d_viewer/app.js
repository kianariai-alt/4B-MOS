import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';

const $ = id => document.getElementById(id);
const fa = value => new Intl.NumberFormat('fa-IR', { maximumFractionDigits: 1 }).format(value);
let renderer;

async function localFile(name) {
  const response = await fetch(new URL(name, import.meta.url), { redirect: 'error', cache: 'no-store' });
  if (!response.ok) throw new Error('artifact_unavailable');
  return response;
}

async function verifiedBinary(name, sha, expectedLength) {
  const response = await localFile(name);
  const raw = await response.arrayBuffer();
  if (raw.byteLength !== expectedLength) throw new Error('artifact_size_mismatch');
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', raw)),
    value => value.toString(16).padStart(2, '0')).join('');
  if (hash !== sha) throw new Error('artifact_hash_mismatch');
  return raw;
}

async function start() {
  const response = await localFile('scene.json');
  const data = await response.json();
  if (data.schema_version !== 'synthetic-knee-viewer-v1' || data.synthetic_only !== true ||
      data.is_clinically_validated !== false || data.segmentation !== 'known_phantom_labels_not_an_inferred_segmentation' ||
      data.surfaces.meshes.length !== 8 || data.structures.length !== 8) throw new Error('unsupported_artifact');
  const [nz, ny, nx] = data.volume.shape_zyx;
  if (![nx, ny, nz].every(n => Number.isInteger(n) && n >= 2 && n <= 96)) throw new Error('invalid_grid');
  const affine = data.volume.affine_lps;
  if (affine.length !== 4 || !affine.every(row => row.length === 4 && row.every(Number.isFinite))) throw new Error('invalid_affine');
  const [voxelBuffer, labelBuffer] = await Promise.all([
    verifiedBinary('volume.f32', data.assets['volume.f32'], nx * ny * nz * 4),
    verifiedBinary('labels.u8', data.assets['labels.u8'], nx * ny * nz),
  ]);
  const view = new DataView(voxelBuffer);
  const voxels = new Float32Array(nx * ny * nz);
  for (let i = 0; i < voxels.length; i++) {
    voxels[i] = view.getFloat32(i * 4, true);
    if (!Number.isFinite(voxels[i])) throw new Error('invalid_voxels');
  }
  const labels = new Uint8Array(labelBuffer);
  if (!labels.every(value => value <= 8)) throw new Error('invalid_labels');
  const palette = new Map(data.structures.map(item => [item.label, item]));
  const cursor = { x: Math.floor(nx / 2), y: Math.floor(ny / 2), z: Math.floor(nz / 2) };
  const index = (i, j, k) => (k * ny + j) * nx + i;
  function lps(i, j, k) {
    return new THREE.Vector3(...affine.slice(0, 3).map(row => row[0] * i + row[1] * j + row[2] * k + row[3]));
  }

  const host = $('viewport');
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.localClippingEnabled = true;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.domElement.id = 'knee-3d-canvas';
  renderer.domElement.tabIndex = 0;
  renderer.domElement.setAttribute('aria-label', 'مدل سه‌بعدی رنگی زانوی ساختگی');
  host.append(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(37, 1, .15, 1000);
  camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = false;
  controls.minDistance = 5;
  controls.maxDistance = 400;
  scene.add(new THREE.HemisphereLight(0xe5f6ff, 0x354453, 2.2));
  const light = new THREE.DirectionalLight(0xfff3e0, 2.8);
  light.position.set(70, -90, 100);
  scene.add(light);
  const fill = new THREE.DirectionalLight(0x9dd7ff, 1.8);
  fill.position.set(-70, 40, 15);
  scene.add(fill);
  const meshes = new Map();
  const clipPlane = new THREE.Plane();
  let mode = 'overview', pending = false, revision = 0;
  function render() {
    pending = false;
    renderer.render(scene, camera);
    renderer.domElement.dataset.frame = String(++revision);
  }
  function schedule() {
    if (!pending) { pending = true; requestAnimationFrame(render); }
  }
  controls.addEventListener('change', schedule);
  for (const item of data.surfaces.meshes) {
    const structure = palette.get(item.label);
    if (!structure || meshes.has(item.label) || !item.vertices_lps_mm.length ||
        item.triangles.length > 250000 || !item.vertices_lps_mm.every(v => v.length === 3 && v.every(Number.isFinite)) ||
        !item.triangles.every(face => face.length === 3 && face.every(i => Number.isInteger(i) && i >= 0 && i < item.vertices_lps_mm.length))) {
      throw new Error('invalid_surface');
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(item.vertices_lps_mm.flat(), 3));
    geometry.setIndex(item.triangles.flat());
    geometry.computeVertexNormals();
    const material = new THREE.MeshStandardMaterial({ color: structure.color, roughness: .55,
      metalness: .02, side: THREE.DoubleSide, transparent: item.label <= 4,
      opacity: item.label <= 3 ? .55 : item.label === 4 ? .88 : 1, depthWrite: item.label > 4 });
    const mesh = new THREE.Mesh(geometry, material);
    scene.add(mesh);
    meshes.set(item.label, mesh);
    const row = document.createElement('label');
    row.className = 'structure-item';
    const swatch = document.createElement('span');
    swatch.className = 'swatch'; swatch.style.backgroundColor = structure.color;
    const title = document.createElement('span'); title.textContent = structure.title;
    const code = document.createElement('small'); code.textContent = structure.code; title.append(code);
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = true;
    checkbox.id = `structure-${item.label}`; checkbox.setAttribute('aria-label', `نمایش ${structure.title}`);
    checkbox.addEventListener('change', () => { mesh.visible = checkbox.checked; schedule(); });
    row.append(swatch, title, checkbox); $('structure-list').append(row);
  }
  const marker = new THREE.Mesh(new THREE.SphereGeometry(.8, 16, 12),
    new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false }));
  marker.renderOrder = 100; scene.add(marker);
  function boneOpacity() {
    const value = Number($('opacity').value) / 100;
    for (const [label, mesh] of meshes) if (label <= 3) {
      mesh.material.opacity = value; mesh.material.transparent = value < 1;
      mesh.material.depthWrite = value === 1; mesh.material.needsUpdate = true;
    }
    $('opacity-value').textContent = `${fa(value * 100)}٪`; schedule();
  }
  $('opacity').addEventListener('input', boneOpacity);
  function clipping() {
    const normal = new THREE.Vector3(...affine.slice(0, 3).map(row => -row[2])).normalize();
    clipPlane.setFromNormalAndCoplanarPoint(normal, lps(0, 0, Number($('clip-index').value)));
    for (const mesh of meshes.values()) mesh.material.clippingPlanes = $('clip').checked ? [clipPlane] : [];
    $('clip-index').disabled = !$('clip').checked; schedule();
  }
  $('clip-index').max = String(nz - 1); $('clip-index').value = String(cursor.z);
  $('clip-index').addEventListener('input', clipping); $('clip').addEventListener('change', clipping);
  const center = lps((nx - 1) / 2, (ny - 1) / 2, (nz - 1) / 2);
  function preset(next) {
    mode = next; controls.enabled = next !== 'inside'; camera.fov = next === 'inside' ? 78 : 37;
    if (next === 'inside') {
      camera.position.copy(center).add(new THREE.Vector3(0, -8, -5));
      camera.lookAt(center.clone().add(new THREE.Vector3(0, 6, -2)));
      $('opacity').value = '15'; boneOpacity();
    } else {
      camera.position.copy(center).add(next === 'front' ? new THREE.Vector3(0, -160, 10) : new THREE.Vector3(100, -145, 85));
      controls.target.copy(center); controls.update();
      $('opacity').value = '55'; boneOpacity();
    }
    camera.updateProjectionMatrix();
    for (const id of ['overview', 'front', 'inside']) {
      $(id).classList.toggle('active', id === next); $(id).setAttribute('aria-pressed', String(id === next));
    }
    $('camera-help').textContent = next === 'inside' ? 'دید داخلیِ مدل ساختگی · نگاه: کشیدن ماوس · حرکت: W A S D · بالا و پایین: R / F' : 'چرخش: کشیدن ماوس · بزرگ‌نمایی: چرخ ماوس';
    renderer.domElement.focus({ preventScroll: true }); schedule();
  }
  for (const id of ['overview', 'front', 'inside']) $(id).addEventListener('click', () => preset(id));
  renderer.domElement.addEventListener('keydown', event => {
    if (mode !== 'inside' || event.ctrlKey || event.metaKey || event.altKey) return;
    const key = event.key.toLowerCase();
    if (!['w', 'a', 's', 'd', 'r', 'f'].includes(key)) return;
    event.preventDefault();
    const forward = camera.getWorldDirection(new THREE.Vector3());
    const right = new THREE.Vector3().crossVectors(forward, camera.up).normalize();
    const direction = key === 'w' ? forward : key === 's' ? forward.negate() : key === 'd' ? right : key === 'a' ? right.negate() : new THREE.Vector3(0, 0, key === 'r' ? 1 : -1);
    camera.position.addScaledVector(direction, .7); schedule();
  });
  let drag;
  renderer.domElement.addEventListener('pointerdown', event => {
    if (mode !== 'inside') return;
    drag = [event.clientX, event.clientY]; renderer.domElement.setPointerCapture(event.pointerId);
  });
  renderer.domElement.addEventListener('pointermove', event => {
    if (mode !== 'inside' || !drag) return;
    camera.rotateOnWorldAxis(new THREE.Vector3(0, 0, 1), -(event.clientX - drag[0]) * .004);
    camera.rotateX(-(event.clientY - drag[1]) * .004);
    drag = [event.clientX, event.clientY]; schedule();
  });
  for (const event of ['pointerup', 'pointercancel', 'lostpointercapture']) renderer.domElement.addEventListener(event, () => { drag = undefined; });
  const [sx, sy, sz] = data.volume.spacing_xyz_mm;
  const layouts = {
    z: { width: nx, height: ny, spacing: [sx, sy], voxel: (u, v) => [u, v, cursor.z], cross: () => [cursor.x, cursor.y] },
    y: { width: nx, height: nz, spacing: [sx, sz], voxel: (u, v) => [u, cursor.y, v], cross: () => [cursor.x, cursor.z] },
    x: { width: ny, height: nz, spacing: [sy, sz], voxel: (u, v) => [cursor.x, u, v], cross: () => [cursor.y, cursor.z] },
  };
  $('window-center').min = data.volume.modality === 'CT' ? '-1000' : '0';
  $('window-center').max = '1200'; $('window-center').value = data.volume.modality === 'CT' ? '100' : '450';
  $('window-width').min = '10'; $('window-width').max = '2500'; $('window-width').value = data.volume.modality === 'CT' ? '2000' : '950';
  function slices() {
    const centerValue = Number($('window-center').value), width = Number($('window-width').value);
    for (const [axis, layout] of Object.entries(layouts)) {
      const canvas = $(`slice-canvas-${axis}`), context = canvas.getContext('2d');
      canvas.width = layout.width; canvas.height = layout.height;
      const physicalRatio = layout.width * layout.spacing[0] / (layout.height * layout.spacing[1]);
      const displayWidth = Math.min(canvas.parentElement.clientWidth, 170 * physicalRatio);
      canvas.style.width = `${displayWidth}px`; canvas.style.height = `${displayWidth / physicalRatio}px`;
      canvas.style.objectFit = 'fill'; canvas.style.marginInline = 'auto';
      const image = context.createImageData(layout.width, layout.height);
      for (let v = 0; v < layout.height; v++) for (let u = 0; u < layout.width; u++) {
        const [i, j, k] = layout.voxel(u, v), offset = index(i, j, k);
        const gray = Math.round(255 * THREE.MathUtils.clamp((voxels[offset] - centerValue) / width + .5, 0, 1));
        let rgb = [gray, gray, gray];
        if ($('overlay').checked && labels[offset]) {
          const color = palette.get(labels[offset]).color;
          rgb = [1, 3, 5].map(start => Math.round(gray * .45 + parseInt(color.slice(start, start + 2), 16) * .55));
        }
        const pixel = (v * layout.width + u) * 4; image.data.set([...rgb, 255], pixel);
      }
      context.putImageData(image, 0, 0);
      const [u, v] = layout.cross(); context.strokeStyle = '#ffffff9f'; context.lineWidth = .5;
      context.beginPath(); context.moveTo(u + .5, 0); context.lineTo(u + .5, layout.height);
      context.moveTo(0, v + .5); context.lineTo(layout.width, v + .5); context.stroke();
      $(`slice-${axis}`).value = String(cursor[axis]); $(`value-${axis}`).textContent = `${cursor[axis] + 1} / ${axis === 'z' ? nz : axis === 'y' ? ny : nx}`;
    }
    marker.position.copy(lps(cursor.x, cursor.y, cursor.z));
    const p = marker.position; $('voxel-location').textContent = `LPS [ ${p.x.toFixed(1)}, ${p.y.toFixed(1)}, ${p.z.toFixed(1)} ] mm`;
    schedule();
  }
  for (const [axis, layout] of Object.entries(layouts)) {
    const slider = $(`slice-${axis}`); slider.max = String((axis === 'z' ? nz : axis === 'y' ? ny : nx) - 1);
    slider.addEventListener('input', () => { cursor[axis] = Number(slider.value); slices(); });
    $(`slice-canvas-${axis}`).addEventListener('pointerdown', event => {
      const canvas = event.currentTarget, rect = canvas.getBoundingClientRect();
      const u = THREE.MathUtils.clamp(Math.floor((event.clientX - rect.left) / rect.width * layout.width), 0, layout.width - 1);
      const v = THREE.MathUtils.clamp(Math.floor((event.clientY - rect.top) / rect.height * layout.height), 0, layout.height - 1);
      [cursor.x, cursor.y, cursor.z] = layout.voxel(u, v); slices();
    });
  }
  for (const id of ['overlay', 'window-center', 'window-width']) $(id).addEventListener('input', slices);
  new ResizeObserver(() => {
    camera.aspect = host.clientWidth / host.clientHeight; camera.updateProjectionMatrix();
    renderer.setSize(host.clientWidth, host.clientHeight, false); slices(); schedule();
  }).observe(host);
  renderer.domElement.addEventListener('webglcontextlost', event => { event.preventDefault(); showFailure(); });
  $('modality').textContent = `${data.volume.modality} · SYNTHETIC`;
  $('spacing').textContent = `${[sx, sy, sz].map(v => v.toFixed(1)).join(' × ')} mm`;
  $('summary').textContent = `${nx} × ${ny} × ${nz} · VTK ${data.surfaces.vtk_version} · 3D surface`;
  $('loading').hidden = true; $('workspace').setAttribute('aria-busy', 'false');
  $('workspace').dataset.ready = 'true'; preset('overview'); slices();
}

function showFailure() {
  $('error').textContent = 'نمایش نمونه ممکن نشد. مرورگر دارای WebGL2 و فایل‌های کامل نمونه را روی یک سرور محلی بررسی کنید.';
  $('error').hidden = false; $('loading').hidden = true;
  $('workspace').setAttribute('aria-busy', 'false');
}
start().catch(() => { renderer?.dispose(); showFailure(); });
