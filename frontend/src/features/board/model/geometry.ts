import type { Device, Issue, PanelModel, Product, Rail } from './types';

/** 1 DIN module = 17.5 mm. */
export const MODULE_MM = 17.5;
/** Screen size of one module at zoom 1. */
export const MODULE_PX = 36;
export const MM_PX = MODULE_PX / MODULE_MM;
export const RAIL_HEIGHT_PX = 128;
export const MOUNT_GRID_MM = 5;

/** Modules a product occupies on a rail: ceil of its (possibly fractional) width. */
export function requiredWidth(modules: number): number {
  return Math.max(0, Math.ceil(modules - 1e-9));
}

export function productModules(p: Product): number {
  return Number(p.modules);
}

export function isPlaceableOnRail(p: Product): boolean {
  return p.din_mountable && requiredWidth(productModules(p)) >= 1;
}

export function railDevices(devices: Device[], railId: number): Device[] {
  return devices.filter((d) => d.railId === railId);
}

/** True if [start, start+width) lies within the rail and overlaps nothing (except `ignore`). */
export function fitsOnRail(
  devices: Device[],
  rail: Rail,
  start: number,
  width: number,
  ignore: ReadonlySet<string> = new Set(),
): boolean {
  if (!Number.isInteger(start) || start < 0 || width < 1 || start + width > rail.capacity) {
    return false;
  }
  for (const d of devices) {
    if (d.railId !== rail.id || ignore.has(d.id) || d.start === null) continue;
    if (start < d.start + d.width && d.start < start + width) return false;
  }
  return true;
}

/** Nearest valid start for a device whose left edge is at `leftModules`; null if none. */
export function snapStart(
  devices: Device[],
  rail: Rail,
  leftModules: number,
  width: number,
  ignore: ReadonlySet<string> = new Set(),
): number | null {
  const wanted = Math.min(Math.max(Math.round(leftModules), 0), Math.max(rail.capacity - width, 0));
  return fitsOnRail(devices, rail, wanted, width, ignore) ? wanted : null;
}

/** First free position scanning rails top to bottom, left to right. */
export function findFreeSpot(
  panel: PanelModel,
  width: number,
  ignore: ReadonlySet<string> = new Set(),
): { railId: number; start: number } | null {
  for (const rail of [...panel.rails].sort((a, b) => a.rowIndex - b.rowIndex)) {
    for (let s = 0; s + width <= rail.capacity; s++) {
      if (fitsOnRail(panel.devices, rail, s, width, ignore)) return { railId: rail.id, start: s };
    }
  }
  return null;
}

export function freeModules(panel: PanelModel): number {
  const total = panel.rails.reduce((n, r) => n + r.capacity, 0);
  const used = panel.devices.reduce((n, d) => (d.railId !== null ? n + d.width : n), 0);
  return total - used;
}

/** Fraction of rail modules still free, 0..1 (1 for a panel without rails). */
export function freeRatio(panel: PanelModel): number {
  const total = panel.rails.reduce((n, r) => n + r.capacity, 0);
  return total === 0 ? 1 : freeModules(panel) / total;
}

export function snapMm(v: number, grid = MOUNT_GRID_MM): number {
  return Math.round(v / grid) * grid;
}

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export function rectsOverlap(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

function rectOf(d: Device): Rect | null {
  if (d.x === null || d.y === null || d.w === null || d.h === null || d.w <= 0 || d.h <= 0) {
    return null;
  }
  return { x: d.x, y: d.y, w: d.w, h: d.h };
}

export function fitsOnMount(
  panel: PanelModel,
  rect: Rect,
  ignore: ReadonlySet<string> = new Set(),
): boolean {
  const { width, height } = panel.area;
  if (width === null || height === null) return false;
  if (rect.x < 0 || rect.y < 0 || rect.x + rect.w > width || rect.y + rect.h > height) return false;
  return !panel.devices.some((d) => {
    if (d.railId !== null || ignore.has(d.id)) return false;
    const r = rectOf(d);
    return r !== null && rectsOverlap(rect, r);
  });
}

/**
 * Client mirror of backend `validate_layout` (same issue codes). Used for instant feedback;
 * the server stays authoritative.
 */
export function validatePanel(panel: PanelModel, products: Map<number, Product>): Issue[] {
  const issues: Issue[] = [];
  const rails = new Map(panel.rails.map((r) => [r.id, r]));
  const onRail = new Map<number, Device[]>();
  const onMount: Device[] = [];
  for (const d of panel.devices) {
    const p = products.get(d.productId);
    if (d.railId !== null) {
      const rail = rails.get(d.railId);
      if (!rail) {
        issues.push({ code: 'unknown_rail', deviceId: d.id });
        continue;
      }
      if (p && !p.din_mountable) issues.push({ code: 'non_din_on_rail', deviceId: d.id });
      const need = p ? requiredWidth(productModules(p)) : d.width;
      if (need < 1) issues.push({ code: 'not_placeable', deviceId: d.id });
      else if (d.width !== need) issues.push({ code: 'width_mismatch', deviceId: d.id });
      if (d.start === null || d.start < 0 || d.start + Math.max(d.width, 1) > rail.capacity) {
        issues.push({ code: 'out_of_bounds', deviceId: d.id });
      }
      onRail.set(rail.id, [...(onRail.get(rail.id) ?? []), d]);
    } else {
      onMount.push(d);
      if (p?.din_mountable) {
        issues.push({ code: 'din_off_rail', deviceId: d.id });
        continue;
      }
      const r = rectOf(d);
      if (!r) {
        issues.push({ code: 'missing_geometry', deviceId: d.id });
      } else if (panel.area.width === null || panel.area.height === null) {
        issues.push({ code: 'no_mounting_panel', deviceId: d.id });
      } else if (
        r.x < 0 ||
        r.y < 0 ||
        r.x + r.w > panel.area.width ||
        r.y + r.h > panel.area.height
      ) {
        issues.push({ code: 'out_of_bounds', deviceId: d.id });
      }
    }
  }
  for (const list of onRail.values()) {
    const items = list
      .filter((d) => d.start !== null && d.start >= 0 && d.width > 0)
      .sort((a, b) => (a.start as number) - (b.start as number) || a.id.localeCompare(b.id));
    items.forEach((a, i) => {
      for (const b of items.slice(i + 1)) {
        if ((b.start as number) >= (a.start as number) + a.width) break;
        issues.push({ code: 'collision', deviceId: b.id, otherId: a.id });
      }
    });
  }
  onMount.forEach((a, i) => {
    const ra = rectOf(a);
    if (!ra) return;
    for (const b of onMount.slice(i + 1)) {
      const rb = rectOf(b);
      if (rb && rectsOverlap(ra, rb))
        issues.push({ code: 'collision', deviceId: b.id, otherId: a.id });
    }
  });
  return issues;
}
