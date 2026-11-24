import type { components } from './schema';
import { api, getAll } from './client';

type S = components['schemas'];
export type User = S['User'];
export type Project = S['Project'];
export type Panel = S['Panel'];
export type Group = S['ConsumerGroup'];
export type PlacementDto = S['Placement'];
export type Product = S['Product'];
export type LayoutVersion = S['LayoutVersion'];
export type Calculation = S['Calculation'];
export type AutolayoutResult = S['AutolayoutResult'];
export type AutolayoutOptions = S['AutolayoutOptionsRequest'];
export type PowerSystem = S['PowerSystem'];
export type PowerCheck = S['PowerCheck'];
export type PowerApplyResult = S['PowerApplyResult'];
export type PvSystem = S['PvSystem'];
export type PvArrayDto = S['PvArray'];
export type PvCheck = S['PvCheck'];
export type Bom = S['Bom'];
export type BomSection = S['BomSection'];
export type PdfDrawing = S['PdfImageRequest'];
export type BulkItem = S['BulkPlacementItemRequest'];

export const auth = {
  me: () => api.get<User>('/auth/me/'),
  login: (email: string, password: string) => api.post<User>('/auth/login/', { email, password }),
  register: (email: string, password: string) =>
    api.post<User>('/auth/register/', { email, password }),
  logout: () => api.post<void>('/auth/logout/'),
};

export const projects = {
  list: () => getAll<Project>('/projects/'),
  get: (id: number) => api.get<Project>(`/projects/${id}/`),
  create: (data: Partial<Project> & { name: string }) => api.post<Project>('/projects/', data),
  update: (id: number, data: Partial<Project>) => api.patch<Project>(`/projects/${id}/`, data),
  remove: (id: number) => api.del(`/projects/${id}/`),
  calc: (id: number) => api.get<Calculation>(`/projects/${id}/calc/`),
};

export const panels = {
  list: (projectId: number) => getAll<Panel>(`/projects/${projectId}/panels/`),
  create: (projectId: number, data: { name: string; kind?: string; enclosure?: number | null }) =>
    api.post<Panel>(`/projects/${projectId}/panels/`, data),
  update: (
    id: number,
    data: {
      name?: string;
      enclosure?: number | null;
      diagram_positions?: Record<string, { x: number; y: number }>;
    },
  ) => api.patch<Panel>(`/panels/${id}/`, data),
  remove: (id: number) => api.del(`/panels/${id}/`),
  placements: (id: number) => getAll<PlacementDto>(`/panels/${id}/placements/`),
  saveBulk: (id: number, placements: BulkItem[]) =>
    api.put<PlacementDto[]>(`/panels/${id}/placements/bulk/`, { placements }),
  autolayout: (id: number, opts: Partial<AutolayoutOptions>) =>
    api.post<AutolayoutResult>(`/panels/${id}/autolayout/`, opts),
  versions: (id: number) => getAll<LayoutVersion>(`/panels/${id}/versions/`),
  createVersion: (id: number, note: string) =>
    api.post<LayoutVersion>(`/panels/${id}/versions/`, { note }),
  restoreVersion: (versionId: number) =>
    api.post<PlacementDto[]>(`/versions/${versionId}/restore/`),
};

export const groups = {
  list: (projectId: number) => getAll<Group>(`/projects/${projectId}/groups/`),
  create: (projectId: number, data: Partial<Group> & { name: string; power_w: number }) =>
    api.post<Group>(`/projects/${projectId}/groups/`, data),
  update: (id: number, data: Partial<Group>) => api.patch<Group>(`/groups/${id}/`, data),
  remove: (id: number) => api.del(`/groups/${id}/`),
  autoselect: (projectId: number) =>
    api.post<Calculation>(`/projects/${projectId}/groups/autoselect/`),
};

export const catalog = {
  products: () => getAll<Product>('/catalog/products/'),
};

export const power = {
  get: (projectId: number) => api.get<PowerSystem>(`/projects/${projectId}/power/`),
  update: (projectId: number, data: Partial<PowerSystem>) =>
    api.patch<PowerSystem>(`/projects/${projectId}/power/`, data),
  check: (projectId: number) => api.get<PowerCheck>(`/projects/${projectId}/power/check/`),
  apply: (projectId: number) => api.post<PowerApplyResult>(`/projects/${projectId}/power/apply/`),
};

export const pv = {
  get: (projectId: number) => api.get<PvSystem>(`/projects/${projectId}/pv/`),
  update: (projectId: number, data: Partial<PvSystem>) =>
    api.patch<PvSystem>(`/projects/${projectId}/pv/`, data),
  check: (projectId: number) => api.get<PvCheck>(`/projects/${projectId}/pv/check/`),
  apply: (projectId: number) => api.post<PowerApplyResult>(`/projects/${projectId}/pv/apply/`),
};

export const bomApi = {
  get: (projectId: number) => api.get<Bom>(`/projects/${projectId}/bom/`),
  xlsx: (projectId: number) => api.download('GET', `/projects/${projectId}/export/xlsx/`),
  pdf: (projectId: number, images: PdfDrawing[] = []) =>
    images.length > 0
      ? api.download('POST', `/projects/${projectId}/export/pdf/`, { images })
      : api.download('GET', `/projects/${projectId}/export/pdf/`),
};
