// Three.js viewer: stacked 5-element Yagi array on a rotator mast.
// Azimuth/elevation slew smoothly to the commanded pointing.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const STATUS_COLORS = {
  online: 0x34d399,
  degraded: 0xfbbf24,
  offline: 0xf87171,
};

export class AntennaView {
  constructor(container) {
    this.container = container;
    this.targetAz = 0;
    this.targetEl = 12;
    this.curAz = 0;
    this.curEl = 12;
    this._disposed = false;

    const w = container.clientWidth || 340;
    const h = container.clientHeight || 218;

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.setSize(w, h);
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.fog = new THREE.Fog(0x060b14, 9, 22);

    this.camera = new THREE.PerspectiveCamera(42, w / h, 0.1, 100);
    this.camera.position.set(4.6, 3.1, 4.6);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0, 1.9, 0);
    this.controls.enablePan = false;
    this.controls.minDistance = 3;
    this.controls.maxDistance = 12;
    this.controls.autoRotate = true;
    this.controls.autoRotateSpeed = 0.7;
    this.controls.enableDamping = true;

    // lights
    this.scene.add(new THREE.HemisphereLight(0x8fb7e8, 0x0a1422, 0.85));
    const key = new THREE.DirectionalLight(0xcfe8ff, 1.5);
    key.position.set(4, 7, 3);
    this.scene.add(key);
    const rim = new THREE.PointLight(0x22d3ee, 6, 14);
    rim.position.set(-3, 2.5, -3);
    this.scene.add(rim);

    this._buildGround();
    this._buildStation();
    this._buildAntenna();

    this._resizeObs = new ResizeObserver(() => this._resize());
    this._resizeObs.observe(container);

    this._animate = this._animate.bind(this);
    this._animate();
  }

  _buildGround() {
    const grid = new THREE.PolarGridHelper(5.5, 12, 7, 48, 0x1d3a5c, 0x16293f);
    grid.position.y = 0.001;
    this.scene.add(grid);

    const disc = new THREE.Mesh(
      new THREE.CircleGeometry(5.5, 48),
      new THREE.MeshStandardMaterial({ color: 0x0a1322, roughness: 0.95 }));
    disc.rotation.x = -Math.PI / 2;
    this.scene.add(disc);

    // N/E/S/W cardinal ticks
    const mk = (txt, x, z) => {
      const c = document.createElement("canvas");
      c.width = c.height = 64;
      const g = c.getContext("2d");
      g.font = "700 38px Inter, sans-serif";
      g.fillStyle = txt === "N" ? "#22d3ee" : "#5b7390";
      g.textAlign = "center";
      g.textBaseline = "middle";
      g.fillText(txt, 32, 34);
      const sp = new THREE.Sprite(new THREE.SpriteMaterial({
        map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false }));
      sp.position.set(x, 0.25, z);
      sp.scale.setScalar(0.62);
      this.scene.add(sp);
    };
    mk("N", 0, -5.0); mk("E", 5.0, 0); mk("S", 0, 5.0); mk("W", -5.0, 0);
  }

  _buildStation() {
    const hut = new THREE.Mesh(
      new THREE.BoxGeometry(1.5, 0.8, 1.1),
      new THREE.MeshStandardMaterial({ color: 0x1b2c44, roughness: 0.6, metalness: 0.3 }));
    hut.position.set(-1.7, 0.4, 0.9);
    this.scene.add(hut);

    const win = new THREE.Mesh(
      new THREE.BoxGeometry(1.51, 0.12, 0.7),
      new THREE.MeshStandardMaterial({
        color: 0x0b1a2c, emissive: 0x22d3ee, emissiveIntensity: 0.55 }));
    win.position.set(-1.7, 0.55, 0.9);
    this.scene.add(win);

    // solar panel
    const panel = new THREE.Mesh(
      new THREE.BoxGeometry(1.1, 0.04, 0.8),
      new THREE.MeshStandardMaterial({ color: 0x10243c, metalness: 0.8, roughness: 0.25 }));
    panel.position.set(-1.7, 0.95, 0.9);
    panel.rotation.z = 0.3;
    this.scene.add(panel);

    // status beacon
    this.beaconMat = new THREE.MeshStandardMaterial({
      color: 0x34d399, emissive: 0x34d399, emissiveIntensity: 1.4 });
    const beacon = new THREE.Mesh(new THREE.SphereGeometry(0.085, 16, 16), this.beaconMat);
    beacon.position.set(-1.7, 0.92 + 0.35, 0.45);
    this.scene.add(beacon);
    this.beaconLight = new THREE.PointLight(0x34d399, 3, 4);
    this.beaconLight.position.copy(beacon.position);
    this.scene.add(this.beaconLight);
  }

  _buildAntenna() {
    const metal = new THREE.MeshStandardMaterial({ color: 0xb8c8da, metalness: 0.85, roughness: 0.3 });
    const dark = new THREE.MeshStandardMaterial({ color: 0x53677e, metalness: 0.7, roughness: 0.45 });

    // mast
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.1, 2.6, 12), dark);
    mast.position.y = 1.3;
    this.scene.add(mast);
    const base = new THREE.Mesh(new THREE.CylinderGeometry(0.32, 0.42, 0.18, 16), dark);
    base.position.y = 0.09;
    this.scene.add(base);

    // guy wires
    const wireMat = new THREE.LineBasicMaterial({ color: 0x2c405c, transparent: true, opacity: 0.7 });
    for (const a of [0.6, 2.2, 3.9, 5.5]) {
      const g = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0, 2.2, 0),
        new THREE.Vector3(Math.cos(a) * 2.4, 0, Math.sin(a) * 2.4),
      ]);
      this.scene.add(new THREE.Line(g, wireMat));
    }

    // yaw group (azimuth) at the masthead
    this.yaw = new THREE.Group();
    this.yaw.position.y = 2.72;
    this.scene.add(this.yaw);

    const rotator = new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.13, 0.3, 12), metal);
    rotator.position.y = -0.1;
    this.yaw.add(rotator);

    // pitch group (elevation)
    this.pitch = new THREE.Group();
    this.pitch.position.y = 0.12;
    this.yaw.add(this.pitch);

    // two stacked yagi booms, forward = -Z (north at yaw 0)
    const elements = [
      { z: 1.0, len: 1.55 },   // reflector (rear)
      { z: 0.35, len: 1.25, driven: true },
      { z: -0.2, len: 1.1 },
      { z: -0.7, len: 1.0 },
      { z: -1.15, len: 0.9 },  // front director
    ];
    const drivenMat = new THREE.MeshStandardMaterial({
      color: 0x9fe8f7, metalness: 0.7, roughness: 0.25,
      emissive: 0x22d3ee, emissiveIntensity: 0.5,
    });
    this.drivenMat = drivenMat;

    for (const yOff of [0.28, -0.28]) {
      const boom = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 2.5, 8), metal);
      boom.rotation.x = Math.PI / 2;
      boom.position.set(0, yOff, -0.1);
      this.pitch.add(boom);
      for (const el of elements) {
        const rod = new THREE.Mesh(
          new THREE.CylinderGeometry(0.018, 0.018, el.len, 8),
          el.driven ? drivenMat : metal);
        rod.rotation.z = Math.PI / 2;
        rod.position.set(0, yOff, el.z - 0.1);
        this.pitch.add(rod);
      }
    }
    // vertical stack brace
    const brace = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.62, 8), metal);
    this.pitch.add(brace);

    // boresight beam hint
    const beamGeo = new THREE.ConeGeometry(0.34, 3.2, 20, 1, true);
    const beamMat = new THREE.MeshBasicMaterial({
      color: 0x22d3ee, transparent: true, opacity: 0.10,
      side: THREE.DoubleSide, depthWrite: false,
    });
    this.beam = new THREE.Mesh(beamGeo, beamMat);
    this.beam.rotation.x = Math.PI / 2;          // axis along -Z
    this.beam.position.set(0, 0, -2.9);
    this.pitch.add(this.beam);
  }

  setPointing(azDeg, elDeg) {
    this.targetAz = azDeg;
    this.targetEl = Math.max(0, Math.min(85, elDeg));
  }

  setStatus(status) {
    const c = STATUS_COLORS[status] ?? STATUS_COLORS.online;
    this.beaconMat.color.setHex(c);
    this.beaconMat.emissive.setHex(c);
    this.beaconLight.color.setHex(c);
    const active = status !== "offline";
    this.drivenMat.emissiveIntensity = active ? 0.5 : 0.05;
    this.beam.visible = active;
  }

  _resize() {
    if (this._disposed) return;
    const w = this.container.clientWidth, h = this.container.clientHeight;
    if (!w || !h) return;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }

  _animate() {
    if (this._disposed) return;
    requestAnimationFrame(this._animate);

    // shortest-path azimuth slew
    let dAz = ((this.targetAz - this.curAz + 540) % 360) - 180;
    this.curAz += dAz * 0.06;
    this.curEl += (this.targetEl - this.curEl) * 0.06;

    this.yaw.rotation.y = -this.curAz * Math.PI / 180;
    this.pitch.rotation.x = this.curEl * Math.PI / 180;

    const t = performance.now() / 1000;
    this.beaconMat.emissiveIntensity = 1.1 + Math.sin(t * 3.2) * 0.5;
    this.beam.material.opacity = 0.08 + Math.sin(t * 2.1) * 0.03;

    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    this._disposed = true;
    this._resizeObs.disconnect();
    this.controls.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
