export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
  ) {
    super(formatApiError(status, body));
  }
}

/** Flatten DRF error bodies (incl. our `layout` / `placements` shapes) into one line. */
export function formatApiError(status: number, body: unknown): string {
  const parts: string[] = [];
  const walk = (v: unknown, path: string): void => {
    if (typeof v === 'string') parts.push(path ? `${path}: ${v}` : v);
    else if (Array.isArray(v)) v.forEach((x) => walk(x, path));
    else if (v && typeof v === 'object') {
      const o = v as Record<string, unknown>;
      if (typeof o.message === 'string' && typeof o.code === 'string') {
        parts.push(`${path ? path + ': ' : ''}${o.message}`);
      } else {
        for (const [k, x] of Object.entries(o))
          walk(x, k === 'detail' || k === 'layout' ? path : k);
      }
    }
  };
  walk(body, '');
  return parts.length > 0 ? parts.join('; ') : `HTTP ${status}`;
}

function cookie(name: string): string | null {
  const m = document.cookie.split('; ').find((c) => c.startsWith(`${name}=`));
  return m ? decodeURIComponent(m.slice(name.length + 1)) : null;
}

async function csrfToken(): Promise<string> {
  const existing = cookie('csrftoken');
  if (existing) return existing;
  const r = await fetch('/api/v1/auth/csrf/', { credentials: 'same-origin' });
  const body = (await r.json()) as { csrfToken: string };
  return cookie('csrftoken') ?? body.csrfToken;
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (method !== 'GET') headers['X-CSRFToken'] = await csrfToken();
  const init: RequestInit = { method, headers, credentials: 'same-origin' };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(`/api/v1${path}`, init);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data: unknown = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, data);
  return data as T;
}

/** File download (XLSX/PDF): returns the blob, throws ApiError on a failure. */
async function download(method: 'GET' | 'POST', path: string, body?: unknown): Promise<Blob> {
  const headers: Record<string, string> = {};
  const init: RequestInit = { method, headers, credentials: 'same-origin' };
  if (method === 'POST') {
    headers['X-CSRFToken'] = await csrfToken();
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body ?? {});
  }
  const res = await fetch(`/api/v1${path}`, init);
  if (!res.ok) {
    const text = await res.text();
    let data: unknown = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = null;
    }
    throw new ApiError(res.status, data);
  }
  return res.blob();
}

export const api = {
  download,
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  del: (path: string) => request<void>('DELETE', path),
};

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/** Follow `next` links until the collection is exhausted. */
export async function getAll<T>(path: string): Promise<T[]> {
  const sep = path.includes('?') ? '&' : '?';
  let url: string | null = `${path}${sep}page_size=500`;
  const out: T[] = [];
  while (url) {
    const page: Page<T> = await api.get<Page<T>>(url.replace(/^.*\/api\/v1/, ''));
    out.push(...page.results);
    url = page.next;
  }
  return out;
}
