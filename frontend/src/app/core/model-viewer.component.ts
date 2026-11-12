import { Component, ElementRef, OnDestroy, effect, input, output, viewChild } from '@angular/core';

/** Native dynamic import (kept out of the bundler): the import map in index.html points `three` at the CDN. */
const load = (spec: string): Promise<any> => (new Function('s', 'return import(s)') as any)(spec);

/** Phase K block 7 — a GLB / glTF, OBJ or IFC model in the browser (Three.js; IFC through web-ifc). Orbit and zoom;
 *  a click on the model emits the point and the camera position (for a pinned comment); comments show as numbered pins.
 *  `link` shares one camera between two viewers (before / after). */
@Component({
  selector: 'app-model-viewer',
  template: `<div #box class="box" [attr.aria-label]="model().title" role="img">
      @if (status) { <div class="status small">{{ status }}</div> }
      @for (p of pins; track $index) { <span class="pin" [style.left.px]="p.x" [style.top.px]="p.y" [title]="p.text">{{ $index + 1 }}</span> }
    </div>`,
  styles: `.box { position: relative; width: 100%; height: 420px; border-radius: 8px; overflow: hidden; background: #1f2430; }
    .status { position: absolute; inset: auto 0 0 0; padding: .4rem .6rem; color: #fff; background: rgba(0,0,0,.45); }
    .pin { position: absolute; transform: translate(-50%, -50%); background: #2563eb; color: #fff; border-radius: 50%; width: 1.5rem; height: 1.5rem;
      display: grid; place-items: center; font-size: .72rem; font-weight: 700; box-shadow: 0 0 0 2px #fff; pointer-events: auto; }`,
})
export class ModelViewerComponent implements OnDestroy {
  model = input.required<any>();
  canComment = input(false);
  link = input<{ cam?: any; listeners: Set<() => void> } | null>(null);
  spot = output<{ point: number[]; camera: number[] }>();
  private box = viewChild<ElementRef<HTMLDivElement>>('box');
  status = 'Loading the 3D viewer…';
  pins: { x: number; y: number; text: string }[] = [];
  private T: any;
  private renderer: any;
  private scene: any;
  private camera: any;
  private controls: any;
  private root: any;
  private frame = 0;
  private builtFor = '';
  private down: [number, number] | null = null;

  constructor() {
    effect(() => {
      const m = this.model();
      const el = this.box()?.nativeElement;
      if (el && m.id + m.comments?.length !== this.builtFor) {
        if (this.builtFor.startsWith(m.id)) this.placePins();
        else this.build(m, el);
        this.builtFor = m.id + m.comments?.length;
      }
    });
  }

  private async build(m: any, el: HTMLDivElement) {
    try {
      const T = (this.T = await load('three'));
      const { OrbitControls } = await load('three/addons/controls/OrbitControls.js');
      this.dispose();
      const w = el.clientWidth, h = el.clientHeight;
      this.renderer = new T.WebGLRenderer({ antialias: true });
      this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
      this.renderer.setSize(w, h);
      el.prepend(this.renderer.domElement);
      this.scene = new T.Scene();
      this.scene.background = new T.Color(0x1f2430);
      this.scene.add(new T.HemisphereLight(0xffffff, 0x444444, 2.2));
      const sun = new T.DirectionalLight(0xffffff, 1.6);
      sun.position.set(5, 10, 7);
      this.scene.add(sun);
      this.camera = new T.PerspectiveCamera(50, w / h, 0.05, 5000);
      this.controls = new OrbitControls(this.camera, this.renderer.domElement);
      this.controls.enableDamping = true;
      this.status = `Loading ${m.format.toUpperCase()} model…`;
      this.root = await this.loadModel(T, m);
      this.scene.add(this.root);
      this.fit();
      this.status = '';
      this.hookLink();
      const el2 = this.renderer.domElement as HTMLCanvasElement;
      el2.addEventListener('pointerdown', (e) => (this.down = [e.clientX, e.clientY]));
      el2.addEventListener('pointerup', (e) => this.click(e));
      const loop = () => {
        this.frame = requestAnimationFrame(loop);
        this.controls.update();
        this.renderer.render(this.scene, this.camera);
        this.placePins();
      };
      loop();
    } catch (e: any) {
      this.status = 'The model could not be shown: ' + (e?.message || e);
    }
  }

  private async loadModel(T: any, m: any) {
    const buf = await (await fetch(m.url, { credentials: 'same-origin' })).arrayBuffer();
    if (m.format === 'glb' || m.format === 'gltf') {
      const { GLTFLoader } = await load('three/addons/loaders/GLTFLoader.js');
      const g = await new GLTFLoader().parseAsync(buf, '');
      return g.scene;
    }
    if (m.format === 'obj') {
      const { OBJLoader } = await load('three/addons/loaders/OBJLoader.js');
      const o = new OBJLoader().parse(new TextDecoder().decode(buf));
      o.traverse((c: any) => c.isMesh && (c.material = new T.MeshStandardMaterial({ color: 0xd8d2c4 })));
      return o;
    }
    // IFC: web-ifc reads the file; every placed geometry becomes a mesh with its IFC colour
    const W = await load('web-ifc');
    const api = new W.IfcAPI();
    api.SetWasmPath('https://cdn.jsdelivr.net/npm/web-ifc@0.0.57/', true);
    await api.Init();
    const id = api.OpenModel(new Uint8Array(buf));
    const group = new T.Group();
    api.StreamAllMeshes(id, (mesh: any) => {
      const placed = mesh.geometries;
      for (let i = 0; i < placed.size(); i++) {
        const pg = placed.get(i);
        const geom = api.GetGeometry(id, pg.geometryExpressID);
        const v = api.GetVertexArray(geom.GetVertexData(), geom.GetVertexDataSize());
        const idx = api.GetIndexArray(geom.GetIndexData(), geom.GetIndexDataSize());
        const pos = new Float32Array(v.length / 2), nor = new Float32Array(v.length / 2);
        for (let k = 0, j = 0; k < v.length; k += 6, j += 3) {
          pos[j] = v[k]; pos[j + 1] = v[k + 1]; pos[j + 2] = v[k + 2];
          nor[j] = v[k + 3]; nor[j + 1] = v[k + 4]; nor[j + 2] = v[k + 5];
        }
        const bg = new T.BufferGeometry();
        bg.setAttribute('position', new T.BufferAttribute(pos, 3));
        bg.setAttribute('normal', new T.BufferAttribute(nor, 3));
        bg.setIndex(new T.BufferAttribute(idx, 1));
        const c = pg.color;
        const mat = new T.MeshStandardMaterial({ color: new T.Color(c.x, c.y, c.z), transparent: c.w < 1, opacity: c.w, side: T.DoubleSide });
        const me = new T.Mesh(bg, mat);
        me.matrix.fromArray(pg.flatTransformation);
        me.matrixAutoUpdate = false;
        group.add(me);
        geom.delete?.();
      }
    });
    api.CloseModel(id);
    return group;
  }

  private fit() {
    const T = this.T;
    const box = new T.Box3().setFromObject(this.root);
    const size = box.getSize(new T.Vector3()).length() || 10;
    const centre = box.getCenter(new T.Vector3());
    this.controls.target.copy(centre);
    this.camera.position.copy(centre).add(new T.Vector3(size * 0.6, size * 0.45, size * 0.6));
    this.camera.near = size / 1000;
    this.camera.far = size * 20;
    this.camera.updateProjectionMatrix();
  }

  /** Before / after: two viewers move together. */
  private hookLink() {
    const l = this.link();
    if (!l) return;
    const sync = () => {
      if (!l.cam || l.cam.owner === this) return;
      this.camera.position.fromArray(l.cam.pos);
      this.controls.target.fromArray(l.cam.target);
    };
    l.listeners.add(sync);
    this.controls.addEventListener('change', () => {
      l.cam = { owner: this, pos: this.camera.position.toArray(), target: this.controls.target.toArray() };
      l.listeners.forEach((f) => f !== sync && f());
      l.cam.owner = null;
    });
  }

  private click(e: PointerEvent) {
    if (!this.canComment() || !this.down || Math.hypot(e.clientX - this.down[0], e.clientY - this.down[1]) > 4) return;
    const T = this.T;
    const r = this.renderer.domElement.getBoundingClientRect();
    const ray = new T.Raycaster();
    ray.setFromCamera(new T.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), this.camera);
    const hit = ray.intersectObject(this.root, true)[0];
    if (!hit) return;
    const round = (a: number[]) => a.map((x) => Math.round(x * 1000) / 1000);
    this.spot.emit({ point: round(hit.point.toArray()), camera: round(this.camera.position.toArray()) });
  }

  private placePins() {
    if (!this.T || !this.camera) return;
    const r = this.renderer.domElement;
    this.pins = (this.model().comments ?? []).map((c: any) => {
      const v = new this.T.Vector3(...c.point).project(this.camera);
      return { x: ((v.x + 1) / 2) * r.clientWidth, y: ((1 - v.y) / 2) * r.clientHeight, text: `${c.author}: ${c.text}`, behind: v.z > 1 };
    }).filter((p: any) => !p.behind);
  }

  private dispose() {
    cancelAnimationFrame(this.frame);
    this.renderer?.dispose();
    this.renderer?.domElement?.remove();
  }

  ngOnDestroy() {
    this.dispose();
  }
}
