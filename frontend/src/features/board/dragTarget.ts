import {
  fitsOnMount,
  fitsOnRail,
  MM_PX,
  MODULE_PX,
  isPlaceableOnRail,
  productModules,
  requiredWidth,
  snapMm,
} from './model/geometry';
import { planMove, type BoardState } from './model/store';
import type { Product, Target } from './model/types';
import type { Hover } from './components/PanelView';

export type DragData =
  | { type: 'palette'; product: Product }
  | { type: 'group'; product: Product | null; groupId: number }
  | { type: 'device'; deviceId: string; panelId: number };

export interface Probe {
  /** Hover descriptor for the ghost, or null when the pointer is outside any panel area. */
  hover: Hover;
  /** Concrete target to apply when valid. */
  target: Target | null;
  trash: boolean;
}

interface Ctx {
  state: Pick<BoardState, 'panels' | 'selection' | 'products'>;
  zoom: number;
  /** Pointer offset inside the dragged item, in screen px, at drag start. */
  grabPx: { x: number; y: number };
}

/** Resolve what is under the pointer and whether the dragged thing may be dropped there. */
export function probe(data: DragData, px: number, py: number, ctx: Ctx): Probe {
  const els = document.elementsFromPoint(px, py);
  if (els.some((e) => (e as HTMLElement).dataset?.trash !== undefined)) {
    return { hover: null, target: null, trash: data.type === 'device' };
  }
  const { state, zoom, grabPx } = ctx;
  const railEl = els.find((e) => (e as HTMLElement).dataset?.railId !== undefined) as
    HTMLElement | undefined;
  const mountEl = els.find((e) => (e as HTMLElement).dataset?.mountPanel !== undefined) as
    HTMLElement | undefined;

  let product: Product | null = null;
  let widthModules = 1;
  let wMm = 50;
  let hMm = 80;
  if (data.type === 'device') {
    const found = Object.values(state.panels)
      .flatMap((p) => p.devices)
      .find((d) => d.id === data.deviceId);
    if (!found) return { hover: null, target: null, trash: false };
    product = state.products.get(found.productId) ?? null;
    widthModules = found.width;
    wMm = found.w ?? wMm;
    hMm = found.h ?? hMm;
  } else {
    product = data.product;
    if (product) {
      widthModules = requiredWidth(productModules(product));
      wMm = product.width_mm ?? wMm;
      hMm = product.height_mm ?? hMm;
    }
  }
  if (!product) return { hover: null, target: null, trash: false };

  const grabModules = data.type === 'device' ? grabPx.x / (MODULE_PX * zoom) : widthModules / 2;

  if (railEl) {
    const rect = railEl.getBoundingClientRect();
    const railId = Number(railEl.dataset.railId);
    const panelId = Number(railEl.dataset.panelId);
    const panel = state.panels[panelId];
    const rail = panel?.rails.find((r) => r.id === railId);
    if (!panel || !rail) return { hover: null, target: null, trash: false };
    const start = Math.round((px - rect.left) / (MODULE_PX * zoom) - grabModules);
    const target: Target = { kind: 'rail', panelId, railId, start };
    let valid: boolean;
    if (data.type === 'device') {
      valid = planMove(state, data.deviceId, target).ok;
    } else {
      valid = isPlaceableOnRail(product) && fitsOnRail(panel.devices, rail, start, widthModules);
    }
    return {
      hover: { panelId, kind: 'rail', railId, start, width: widthModules, valid },
      target,
      trash: false,
    };
  }
  if (mountEl) {
    const rect = mountEl.getBoundingClientRect();
    const panelId = Number(mountEl.dataset.mountPanel);
    const panel = state.panels[panelId];
    if (!panel) return { hover: null, target: null, trash: false };
    const gx = data.type === 'device' ? grabPx.x / (MM_PX * zoom) : wMm / 2;
    const gy = data.type === 'device' ? grabPx.y / (MM_PX * zoom) : hMm / 2;
    const x = snapMm((px - rect.left) / (MM_PX * zoom) - gx);
    const y = snapMm((py - rect.top) / (MM_PX * zoom) - gy);
    const target: Target = { kind: 'mount', panelId, x, y };
    let valid: boolean;
    if (data.type === 'device') {
      valid = planMove(state, data.deviceId, target).ok;
    } else {
      valid = !product.din_mountable && fitsOnMount(panel, { x, y, w: wMm, h: hMm });
    }
    return { hover: { panelId, kind: 'mount', x, y, w: wMm, h: hMm, valid }, target, trash: false };
  }
  return { hover: null, target: null, trash: false };
}
