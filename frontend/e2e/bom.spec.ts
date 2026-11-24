import { readFileSync } from 'node:fs';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

interface Json {
  [k: string]: unknown;
}

async function api(
  req: APIRequestContext,
  method: 'get' | 'post' | 'patch',
  path: string,
  data?: Json,
) {
  const csrf = (await req.storageState()).cookies.find((c) => c.name === 'csrftoken')?.value ?? '';
  const res = await req[method](`/api/v1${path}`, {
    data,
    headers: { 'X-CSRFToken': csrf, Referer: 'http://localhost:5173/' },
  });
  expect(res.ok(), `${method} ${path}: ${await res.text()}`).toBeTruthy();
  return (await res.json()) as Json;
}

async function productId(req: APIRequestContext, category: string, sku: string): Promise<number> {
  const r = (await api(req, 'get', `/catalog/products/?category=${category}&page_size=200`)) as {
    results: { id: number; sku: string }[];
  };
  const hit = r.results.find((p) => p.sku === sku);
  expect(hit, sku).toBeTruthy();
  return hit!.id;
}

async function seed(page: Page): Promise<number> {
  const req = page.request;
  await api(req, 'get', '/auth/csrf/');
  const email = `bom-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  await api(req, 'post', '/auth/register/', { email, password: 'Pass-12345-xyz' });
  const project = await api(req, 'post', '/projects/', { name: 'Спецификация' });
  const id = project.id as number;
  const enclosures = (await api(
    req,
    'get',
    '/catalog/products/?category=enclosure&page_size=100',
  )) as { results: { id: number; sku: string; electrical: { rows: number } }[] };
  const enc = enclosures.results.find((e) => e.electrical.rows === 2 && e.sku.includes('24'));
  const panel = await api(req, 'post', `/projects/${id}/panels/`, {
    name: 'ГРЩ',
    kind: 'main',
    enclosure: enc?.id,
  });
  await api(req, 'post', `/projects/${id}/groups/`, {
    name: 'Розетки',
    power_w: 3000,
    type: 'sockets',
  });
  await api(req, 'post', `/projects/${id}/groups/autoselect/`);
  await api(req, 'post', `/panels/${panel.id}/autolayout/`, {});
  await api(req, 'patch', `/projects/${id}/pv/`, {
    module: await productId(req, 'pv_module', 'JAM72S30-550/MR'),
    inverter: await productId(req, 'inverter', 'SPH-10000TL3-BH'),
    arrays: [
      { mppt: 1, series: 14, strings: 1 },
      { mppt: 2, series: 14, strings: 1 },
    ],
  });
  return id;
}

test.describe('bill of materials', () => {
  let projectId = 0;

  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 1000 });
    projectId = await seed(page);
  });

  test('page shows sections, totals add up, and exports download', async ({ page }) => {
    await page.goto(`/projects/${projectId}/bom`);
    await expect(page.getByTestId('bom-page')).toBeVisible();
    await expect(page.getByTestId('section-boards')).toBeVisible();
    await expect(page.getByTestId('section-solar')).toBeVisible();
    await expect(
      page.getByTestId('section-solar').locator('[data-sku="SPH-10000TL3-BH"]'),
    ).toBeVisible();

    const num = async (id: string) =>
      Number(
        ((await page.getByTestId(id).textContent()) ?? '').replace(/[^\d,]/g, '').replace(',', '.'),
      );
    const boards = await num('total-boards');
    const solar = await num('total-solar');
    expect(boards).toBeGreaterThan(0);
    expect(solar).toBeGreaterThan(0);
    expect(await num('bom-grand')).toBeCloseTo(boards + solar, 2);

    const [xlsx] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('export-xlsx').click(),
    ]);
    expect(xlsx.suggestedFilename()).toBe(`specification-${projectId}.xlsx`);
    expect(
      readFileSync((await xlsx.path()) as string)
        .subarray(0, 2)
        .toString(),
    ).toBe('PK');

    const [pdf] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('export-pdf').click(),
    ]);
    expect(
      readFileSync((await pdf.path()) as string)
        .subarray(0, 4)
        .toString(),
    ).toBe('%PDF');
  });

  test('PDF from the editor carries the board view and the diagram', async ({ page }) => {
    await page.goto(`/projects/${projectId}/bom`);
    const [plain] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('export-pdf').click(),
    ]);
    const plainSize = readFileSync((await plain.path()) as string).length;

    await page.goto(`/projects/${projectId}/board`);
    await expect(page.getByTestId('panel')).toBeVisible();
    const [withDrawings] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('export-pdf-board').click(),
    ]);
    const bytes = readFileSync((await withDrawings.path()) as string);
    expect(bytes.subarray(0, 4).toString()).toBe('%PDF');
    expect(bytes.length).toBeGreaterThan(plainSize);
  });

  test('editor sidebar total includes the solar section from the server', async ({ page }) => {
    await page.goto(`/projects/${projectId}/board`);
    await expect(page.getByTestId('panel')).toBeVisible();
    const grand = async () =>
      Number(
        ((await page.getByTestId('bom-total').textContent()) ?? '')
          .replace(/[^\d,]/g, '')
          .replace(',', '.'),
      );
    await expect.poll(grand).toBeGreaterThan(100000); // 28 modules + hybrid inverter
  });
});
