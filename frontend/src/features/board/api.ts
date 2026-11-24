import { catalog, groups, panels as panelsApi, projects, type BulkItem } from '../../api/endpoints';
import type { Panel, PlacementDto, Project } from '../../api/endpoints';
import type { Device, Group, PanelModel, Product } from './model/types';

export function placementToDevice(p: PlacementDto): Device {
  return {
    id: `s${p.id}`,
    serverId: p.id,
    productId: p.product,
    railId: p.rail ?? null,
    start: p.start_module ?? null,
    width: p.width_modules ?? 0,
    x: p.x_mm ?? null,
    y: p.y_mm ?? null,
    w: p.w_mm ?? null,
    h: p.h_mm ?? null,
    groupId: p.group ?? null,
    label: p.label ?? '',
  };
}

export function panelToModel(
  p: Panel,
  devices: Device[],
): Omit<PanelModel, 'devices'> & {
  devices: Device[];
} {
  const area = (p as Panel & { mounting_area_mm?: { width: number | null; height: number | null } })
    .mounting_area_mm;
  return {
    id: p.id,
    name: p.name,
    kind: p.kind ?? 'main',
    enclosureId: p.enclosure ?? null,
    ip: p.ip ?? 40,
    rails: p.rails.map((r) => ({ id: r.id, rowIndex: r.row_index, capacity: r.capacity_modules })),
    area: { width: area?.width ?? null, height: area?.height ?? null },
    devices,
  };
}

export function deviceToItem(d: Device): BulkItem {
  const item: BulkItem = {
    product: d.productId,
    rail: d.railId,
    group: d.groupId,
    start_module: d.start,
    width_modules: d.width,
    x_mm: d.x,
    y_mm: d.y,
    w_mm: d.w,
    h_mm: d.h,
    label: d.label,
  };
  if (d.serverId !== null) item.id = d.serverId;
  return item;
}

export interface LoadedBoard {
  project: Project;
  panels: PanelModel[];
  products: Product[];
  groups: Group[];
}

export async function loadBoard(projectId: number): Promise<LoadedBoard> {
  const [project, panelList, products, groupList] = await Promise.all([
    projects.get(projectId),
    panelsApi.list(projectId),
    catalog.products(),
    groups.list(projectId),
  ]);
  const panels = await Promise.all(
    panelList.map(async (p) => {
      const placements = await panelsApi.placements(p.id);
      return panelToModel(p, placements.map(placementToDevice));
    }),
  );
  return { project, panels, products, groups: groupList };
}

export async function reloadPanel(panelId: number, projectId: number): Promise<PanelModel> {
  const panelList = await panelsApi.list(projectId);
  const p = panelList.find((x) => x.id === panelId);
  if (!p) throw new Error('panel not found');
  const placements = await panelsApi.placements(panelId);
  return panelToModel(p, placements.map(placementToDevice));
}

/** Autosave transport: returns server ids in payload order. */
export async function savePanel(
  panelId: number,
  devices: Device[],
): Promise<{ id: string; serverId: number }[]> {
  const saved = await panelsApi.saveBulk(panelId, devices.map(deviceToItem));
  return devices.map((d, i) => ({ id: d.id, serverId: (saved[i] as PlacementDto).id }));
}
