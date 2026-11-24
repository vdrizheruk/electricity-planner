import { createStore, type StoreApi } from 'zustand/vanilla';
import {
  fitsOnMount,
  fitsOnRail,
  findFreeSpot,
  isPlaceableOnRail,
  requiredWidth,
  productModules,
  snapMm,
} from './geometry';
import type { Device, Group, PanelModel, Product, Target } from './types';

export type Snapshot = Record<number, Device[]>;
export type Fail =
  'unknown' | 'collision' | 'out_of_bounds' | 'incompatible' | 'no_space' | 'empty';
export type Result<T = void> = { ok: true; value: T } | { ok: false; reason: Fail };

export type SaveState = 'idle' | 'saving' | 'saved' | 'error';

/** Product categories a consumer group may be bound to (mirrors the backend rule). */
export const GROUP_BINDABLE = new Set(['mcb', 'rcbo', 'rcd', 'contactor']);
const HISTORY_LIMIT = 100;
const DEFAULT_MOUNT_MM = { w: 50, h: 80 };

export interface BoardState {
  panels: Record<number, PanelModel>;
  order: number[];
  products: Map<number, Product>;
  groups: Group[];
  selection: string[];
  clipboard: Device[];
  past: Snapshot[];
  future: Snapshot[];
  /** Bumped on every change of a panel's devices; autosave compares against it. */
  revisions: Record<number, number>;
  seq: number;
  view: { zoom: number; x: number; y: number };
  save: { state: SaveState; error?: string };

  load(input: { panels: PanelModel[]; products: Product[]; groups: Group[] }): void;
  setGroups(groups: Group[]): void;
  addProduct(
    product: Product,
    target: Target,
    extra?: { groupId?: number | null; label?: string },
  ): Result<string>;
  moveDevices(anchorId: string, target: Target): Result;
  removeDevices(ids: string[]): Result;
  setGroup(deviceId: string, groupId: number | null): Result;
  setLabel(deviceId: string, label: string): void;
  replacePanelDevices(panelId: number, panel: Omit<PanelModel, 'devices'>, devices: Device[]): void;
  select(id: string, mode?: 'replace' | 'toggle'): void;
  selectMany(ids: string[]): void;
  clearSelection(): void;
  copy(): Result<number>;
  paste(panelId: number): Result<string[]>;
  undo(): boolean;
  redo(): boolean;
  markSaved(panelId: number, sent: { id: string; serverId: number }[]): void;
  setSave(state: SaveState, error?: string): void;
  setView(view: Partial<BoardState['view']>): void;
}

export type BoardStore = StoreApi<BoardState>;

function snapshot(panels: Record<number, PanelModel>): Snapshot {
  const out: Snapshot = {};
  for (const [id, p] of Object.entries(panels)) out[Number(id)] = p.devices;
  return out;
}

function clone(d: Device, id: string): Device {
  return { ...d, id, serverId: null };
}

function findIn(
  panels: Record<number, PanelModel>,
  id: string,
): { panel: PanelModel; device: Device } | null {
  for (const p of Object.values(panels)) {
    const d = p.devices.find((x) => x.id === id);
    if (d) return { panel: p, device: d };
  }
  return null;
}

export function planMove(
  s: Pick<BoardState, 'panels' | 'selection'>,
  anchorId: string,
  target: Target,
): Result<Record<number, Device[]> | null> {
  const found = findIn(s.panels, anchorId);
  if (!found) return { ok: false, reason: 'unknown' };
  const { panel: srcPanel, device: anchor } = found;
  const dst = s.panels[target.panelId];
  if (!dst) return { ok: false, reason: 'unknown' };

  const group = s.selection.includes(anchorId) ? s.selection : [anchorId];
  const moving = group
    .map((id) => findIn(s.panels, id))
    .filter((f): f is { panel: PanelModel; device: Device } => f !== null)
    .filter(
      (f) => f.panel.id === srcPanel.id && (f.device.railId === null) === (anchor.railId === null),
    )
    .map((f) => f.device);
  if (moving.length > 1 && dst.id !== srcPanel.id) return { ok: false, reason: 'incompatible' };
  const ids = new Set(moving.map((d) => d.id));

  const updated = new Map<string, Device>();
  if (target.kind === 'rail') {
    if (anchor.railId === null || anchor.start === null)
      return { ok: false, reason: 'incompatible' };
    const rowOf = (railId: number, p: PanelModel) =>
      p.rails.find((r) => r.id === railId)?.rowIndex ?? -1;
    const dstRail = dst.rails.find((r) => r.id === target.railId);
    if (!dstRail) return { ok: false, reason: 'unknown' };
    const dRow = dstRail.rowIndex - rowOf(anchor.railId, srcPanel);
    const dStart = target.start - anchor.start;
    for (const d of moving) {
      const row = rowOf(d.railId as number, srcPanel) + dRow;
      const rail = dst.rails.find((r) => r.rowIndex === row);
      if (!rail || d.start === null) return { ok: false, reason: 'out_of_bounds' };
      updated.set(d.id, { ...d, railId: rail.id, start: d.start + dStart });
    }
    // validate against everything that stays + the other moved devices
    const rest = dst.devices.filter((d) => !ids.has(d.id));
    const placed: Device[] = [...rest];
    for (const d of updated.values()) {
      const rail = dst.rails.find((r) => r.id === d.railId) as NonNullable<
        (typeof dst.rails)[number]
      >;
      if (!fitsOnRail(placed, rail, d.start as number, d.width)) {
        const inside = (d.start as number) >= 0 && (d.start as number) + d.width <= rail.capacity;
        return { ok: false, reason: inside ? 'collision' : 'out_of_bounds' };
      }
      placed.push(d);
    }
  } else {
    if (anchor.railId !== null || anchor.x === null || anchor.y === null) {
      return { ok: false, reason: 'incompatible' };
    }
    const dx = snapMm(target.x) - anchor.x;
    const dy = snapMm(target.y) - anchor.y;
    const rest = dst.devices.filter((d) => !ids.has(d.id));
    const probe = { ...dst, devices: rest };
    for (const d of moving) {
      if (d.x === null || d.y === null || d.w === null || d.h === null) {
        return { ok: false, reason: 'incompatible' };
      }
      const nd = { ...d, x: d.x + dx, y: d.y + dy };
      if (!fitsOnMount(probe, { x: nd.x, y: nd.y, w: d.w, h: d.h })) {
        return { ok: false, reason: 'out_of_bounds' };
      }
      probe.devices = [...probe.devices, nd];
      updated.set(d.id, nd);
    }
  }

  const unchanged =
    dst.id === srcPanel.id &&
    moving.every((d) => {
      const u = updated.get(d.id);
      return u && u.railId === d.railId && u.start === d.start && u.x === d.x && u.y === d.y;
    });
  if (unchanged) return { ok: true, value: null }; // dropped back where it was
  const next: Record<number, Device[]> = {};
  if (dst.id === srcPanel.id) {
    next[dst.id] = srcPanel.devices.map((d) => updated.get(d.id) ?? d);
  } else {
    next[srcPanel.id] = srcPanel.devices.filter((d) => !ids.has(d.id));
    next[dst.id] = [...dst.devices, ...updated.values()];
  }
  return { ok: true, value: next };
}

export function createBoardStore(): BoardStore {
  return createStore<BoardState>()((set, get) => {
    /** Apply a mutation of device lists, recording undo history and bumping revisions. */
    function commit(next: Record<number, Device[]>, selection?: string[]): void {
      const s = get();
      const panels = { ...s.panels };
      const revisions = { ...s.revisions };
      for (const [idStr, devices] of Object.entries(next)) {
        const id = Number(idStr);
        const cur = panels[id];
        if (!cur) continue;
        panels[id] = { ...cur, devices };
        revisions[id] = (revisions[id] ?? 0) + 1;
      }
      set({
        panels,
        revisions,
        past: [...s.past, snapshot(s.panels)].slice(-HISTORY_LIMIT),
        future: [],
        ...(selection ? { selection } : {}),
      });
    }

    function findDevice(id: string): { panel: PanelModel; device: Device } | null {
      for (const p of Object.values(get().panels)) {
        const d = p.devices.find((x) => x.id === id);
        if (d) return { panel: p, device: d };
      }
      return null;
    }

    function nextId(): string {
      const n = get().seq + 1;
      set({ seq: n });
      return `n${n}`;
    }

    function restore(snap: Snapshot): void {
      const s = get();
      const panels = { ...s.panels };
      const revisions = { ...s.revisions };
      for (const [idStr, devices] of Object.entries(snap)) {
        const id = Number(idStr);
        const cur = panels[id];
        if (cur && cur.devices !== devices) {
          panels[id] = { ...cur, devices };
          revisions[id] = (revisions[id] ?? 0) + 1;
        }
      }
      const alive = new Set(Object.values(panels).flatMap((p) => p.devices.map((d) => d.id)));
      set({ panels, revisions, selection: s.selection.filter((id) => alive.has(id)) });
    }

    return {
      panels: {},
      order: [],
      products: new Map(),
      groups: [],
      selection: [],
      clipboard: [],
      past: [],
      future: [],
      revisions: {},
      seq: 0,
      view: { zoom: 1, x: 0, y: 0 },
      save: { state: 'idle' },

      load({ panels, products, groups }) {
        set({
          panels: Object.fromEntries(panels.map((p) => [p.id, p])),
          order: panels.map((p) => p.id),
          products: new Map(products.map((p) => [p.id, p])),
          groups,
          selection: [],
          past: [],
          future: [],
          revisions: Object.fromEntries(panels.map((p) => [p.id, 0])),
        });
      },

      setGroups(groups) {
        set({ groups });
      },

      addProduct(product, target, extra = {}) {
        const panel = get().panels[target.panelId];
        if (!panel) return { ok: false, reason: 'unknown' };
        const id = nextId();
        const base: Device = {
          id,
          serverId: null,
          productId: product.id,
          railId: null,
          start: null,
          width: 0,
          x: null,
          y: null,
          w: null,
          h: null,
          groupId: extra.groupId ?? null,
          label: extra.label ?? '',
        };
        if (extra.groupId != null && !GROUP_BINDABLE.has(product.category.code)) {
          return { ok: false, reason: 'incompatible' };
        }
        let device: Device;
        if (target.kind === 'rail') {
          if (!isPlaceableOnRail(product)) return { ok: false, reason: 'incompatible' };
          const rail = panel.rails.find((r) => r.id === target.railId);
          if (!rail) return { ok: false, reason: 'unknown' };
          const width = requiredWidth(productModules(product));
          if (!fitsOnRail(panel.devices, rail, target.start, width)) {
            const inside = target.start >= 0 && target.start + width <= rail.capacity;
            return { ok: false, reason: inside ? 'collision' : 'out_of_bounds' };
          }
          device = { ...base, railId: rail.id, start: target.start, width };
        } else {
          if (product.din_mountable) return { ok: false, reason: 'incompatible' };
          const w = product.width_mm ?? DEFAULT_MOUNT_MM.w;
          const h = product.height_mm ?? DEFAULT_MOUNT_MM.h;
          const rect = { x: snapMm(target.x), y: snapMm(target.y), w, h };
          if (!fitsOnMount(panel, rect)) return { ok: false, reason: 'out_of_bounds' };
          device = { ...base, x: rect.x, y: rect.y, w, h };
        }
        commit({ [panel.id]: [...panel.devices, device] }, [id]);
        return { ok: true, value: id };
      },

      moveDevices(anchorId, target) {
        const plan = planMove(get(), anchorId, target);
        if (!plan.ok) return plan;
        if (plan.value !== null) commit(plan.value);
        return { ok: true, value: undefined };
      },

      removeDevices(ids) {
        const set_ = new Set(ids);
        const next: Record<number, Device[]> = {};
        for (const p of Object.values(get().panels)) {
          if (p.devices.some((d) => set_.has(d.id))) {
            next[p.id] = p.devices.filter((d) => !set_.has(d.id));
          }
        }
        if (Object.keys(next).length === 0) return { ok: false, reason: 'empty' };
        commit(next);
        set({ selection: get().selection.filter((id) => !set_.has(id)) });
        return { ok: true, value: undefined };
      },

      setGroup(deviceId, groupId) {
        const found = findDevice(deviceId);
        if (!found) return { ok: false, reason: 'unknown' };
        const product = get().products.get(found.device.productId);
        if (groupId !== null && (!product || !GROUP_BINDABLE.has(product.category.code))) {
          return { ok: false, reason: 'incompatible' };
        }
        commit({
          [found.panel.id]: found.panel.devices.map((d) =>
            d.id === deviceId ? { ...d, groupId } : d,
          ),
        });
        return { ok: true, value: undefined };
      },

      setLabel(deviceId, label) {
        const found = findDevice(deviceId);
        if (!found) return;
        commit({
          [found.panel.id]: found.panel.devices.map((d) =>
            d.id === deviceId ? { ...d, label } : d,
          ),
        });
      },

      replacePanelDevices(panelId, panel, devices) {
        const cur = get().panels[panelId];
        if (!cur) return;
        const s = get();
        set({
          panels: { ...s.panels, [panelId]: { ...cur, ...panel, devices } },
          revisions: { ...s.revisions, [panelId]: (s.revisions[panelId] ?? 0) + 1 },
          past: [...s.past, snapshot(s.panels)].slice(-HISTORY_LIMIT),
          future: [],
          selection: [],
        });
      },

      select(id, mode = 'replace') {
        const sel = get().selection;
        if (mode === 'toggle') {
          set({ selection: sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id] });
        } else {
          set({ selection: [id] });
        }
      },
      selectMany(ids) {
        set({ selection: ids });
      },
      clearSelection() {
        set({ selection: [] });
      },

      copy() {
        const s = get();
        const sel = new Set(s.selection);
        const items = Object.values(s.panels).flatMap((p) =>
          p.devices.filter((d) => sel.has(d.id)),
        );
        if (items.length === 0) return { ok: false, reason: 'empty' };
        set({ clipboard: items });
        return { ok: true, value: items.length };
      },

      paste(panelId) {
        const s = get();
        const panel = s.panels[panelId];
        if (!panel) return { ok: false, reason: 'unknown' };
        if (s.clipboard.length === 0) return { ok: false, reason: 'empty' };
        let working: PanelModel = panel;
        const created: Device[] = [];
        let seq = s.seq;
        for (const src of s.clipboard) {
          seq += 1;
          const id = `n${seq}`;
          let nd: Device;
          if (src.railId !== null) {
            const spot = findFreeSpot(working, src.width);
            if (!spot) return { ok: false, reason: 'no_space' };
            nd = { ...clone(src, id), railId: spot.railId, start: spot.start, groupId: null };
          } else {
            const w = src.w ?? DEFAULT_MOUNT_MM.w;
            const h = src.h ?? DEFAULT_MOUNT_MM.h;
            let found: { x: number; y: number } | null = null;
            const maxX = (working.area.width ?? 0) - w;
            const maxY = (working.area.height ?? 0) - h;
            for (let y = 0; y <= maxY && !found; y += MOUNT_STEP) {
              for (let x = 0; x <= maxX; x += MOUNT_STEP) {
                if (fitsOnMount(working, { x, y, w, h })) {
                  found = { x, y };
                  break;
                }
              }
            }
            if (!found) return { ok: false, reason: 'no_space' };
            nd = { ...clone(src, id), x: found.x, y: found.y, w, h, groupId: null };
          }
          working = { ...working, devices: [...working.devices, nd] };
          created.push(nd);
        }
        set({ seq });
        commit(
          { [panelId]: working.devices },
          created.map((d) => d.id),
        );
        return { ok: true, value: created.map((d) => d.id) };
      },

      undo() {
        const s = get();
        const prev = s.past[s.past.length - 1];
        if (!prev) return false;
        set({ past: s.past.slice(0, -1), future: [snapshot(s.panels), ...s.future] });
        restore(prev);
        return true;
      },

      redo() {
        const s = get();
        const next = s.future[0];
        if (!next) return false;
        set({ future: s.future.slice(1), past: [...s.past, snapshot(s.panels)] });
        restore(next);
        return true;
      },

      markSaved(panelId, sent) {
        const s = get();
        const panel = s.panels[panelId];
        if (!panel) return;
        const ids = new Map(sent.map((x) => [x.id, x.serverId]));
        // Server ids do not change the layout: no history entry, no revision bump.
        const patch = (list: Device[]): Device[] =>
          list.map((d) => (ids.has(d.id) ? { ...d, serverId: ids.get(d.id) ?? d.serverId } : d));
        const patchSnap = (snap: Snapshot): Snapshot =>
          snap[panelId] ? { ...snap, [panelId]: patch(snap[panelId]) } : snap;
        set({
          panels: { ...s.panels, [panelId]: { ...panel, devices: patch(panel.devices) } },
          past: s.past.map(patchSnap),
          future: s.future.map(patchSnap),
        });
      },

      setSave(state, error) {
        set({ save: error ? { state, error } : { state } });
      },

      setView(view) {
        set({ view: { ...get().view, ...view } });
      },
    };
  });
}

const MOUNT_STEP = 5;

export type { Device };
