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

async function seed(page: Page): Promise<number> {
  const req = page.request;
  await api(req, 'get', '/auth/csrf/');
  const email = `pw-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  await api(req, 'post', '/auth/register/', { email, password: 'Pass-12345-xyz' });
  const project = await api(req, 'post', '/projects/', { name: 'Солнце', grid: '3ph' });
  return project.id as number;
}

async function choose(page: Page, testId: string, text: RegExp) {
  const select = page.getByTestId(testId);
  const value = await select.locator('option', { hasText: text }).first().getAttribute('value');
  await select.selectOption(value as string);
}

const finding = (page: Page, code: string) => page.locator(`[data-code="${code}"]`);

test.describe('photovoltaics', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 1100 });
    const id = await seed(page);
    await page.goto(`/projects/${id}/pv`);
    await expect(page.getByTestId('pv-page')).toBeVisible();
    await choose(page, 'pv-module', /JAM72S30-550/);
    await choose(page, 'pv-inverter', /SPH-10000TL3/);
  });

  test('strings are checked live against the MPPT limits', async ({ page }) => {
    await page.getByTestId('add-array').click();
    await page.getByTestId('a-series').fill('14');
    await expect(page.getByTestId('pv-status')).toHaveAttribute('data-ok', 'true');
    await expect(page.getByTestId('pv-modules')).toHaveText('14');
    await expect(page.getByTestId('pv-kwp')).toContainText('7.70');
    await expect(page.getByTestId('pv-yield')).toContainText('кВт');

    // too many modules: cold open-circuit voltage exceeds the 1000 V input
    await page.getByTestId('a-series').fill('20');
    await expect(finding(page, 'VOC_COLD')).toBeVisible();
    await expect(page.getByTestId('pv-status')).toHaveAttribute('data-ok', 'false');
    await expect(page.getByTestId('pv-apply')).toBeDisabled();

    // two parallel strings exceed the 20 A short-circuit limit
    await page.getByTestId('a-series').fill('14');
    await page.getByTestId('a-strings').fill('2');
    await expect(finding(page, 'ISC_HIGH')).toBeVisible();
  });

  test('DC/AC above 1.3 is highlighted, gPV fuses appear above two strings', async ({ page }) => {
    await page.getByTestId('add-array').click();
    await page.getByTestId('a-series').fill('18');
    await page.getByTestId('add-array').click();
    await page.getByTestId('a-series').nth(1).fill('18');
    await expect(finding(page, 'DC_AC_HIGH')).toBeVisible();
    await expect(page.getByTestId('pv-dcac')).toContainText('1.98');

    await choose(page, 'pv-module', /JAM54S30-410/);
    await choose(page, 'pv-inverter', /SUN2000-15KTL/);
    await page.getByTestId('a-remove').nth(1).click();
    await page.getByTestId('a-series').fill('12');
    await page.getByTestId('a-strings').fill('3');
    await expect(page.locator('[data-role="dc_fuse"]')).toBeVisible();
  });

  test('a valid system builds the DC box', async ({ page }) => {
    await page.getByTestId('add-array').click();
    await page.getByTestId('a-series').fill('14');
    await expect(page.getByTestId('pv-status')).toHaveAttribute('data-ok', 'true');
    await expect(page.locator('[data-role="dc_isolator"]')).toBeVisible();
    await expect(page.locator('[data-role="dc_spd"]')).toBeVisible();
    await expect(page.getByTestId('pv-total')).not.toHaveText('0.00 ₴');
    await page.getByTestId('pv-apply').click();
    await expect(page.getByTestId('pv-applied-link')).toBeVisible();
  });
});
