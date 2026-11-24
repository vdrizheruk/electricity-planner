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
  const project = await api(req, 'post', '/projects/', { name: 'Резерв' });
  for (const [name, type, power] of [
    ['Свет', 'lighting', 400],
    ['Розетки', 'sockets', 3000],
    ['Кондиционер', 'ac', 2000],
    ['Бойлер', 'boiler', 2000],
  ] as const) {
    await api(req, 'post', `/projects/${project.id}/groups/`, {
      name,
      type,
      power_w: power,
      cos_phi: '0.8',
      backed_up: name !== 'Бойлер',
    });
  }
  return project.id as number;
}

async function choose(page: Page, testId: string, text: RegExp) {
  const select = page.getByTestId(testId);
  const value = await select.locator('option', { hasText: text }).first().getAttribute('value');
  await select.selectOption(value as string);
}

test.describe('backup power', () => {
  let projectId = 0;

  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 1000 });
    projectId = await seed(page);
    await page.goto(`/projects/${projectId}/power`);
    await expect(page.getByTestId('power-page')).toBeVisible();
  });

  const finding = (page: Page, code: string) => page.locator(`[data-code="${code}"]`);

  test('generator without ATS is a blocking parallel-operation error', async ({ page }) => {
    await choose(page, 'generator', /DHY-8500SE/);
    await expect(finding(page, 'PARALLEL_GEN_GRID')).toBeVisible();
    await expect(page.getByTestId('power-status')).toHaveAttribute('data-ok', 'false');
    await expect(page.getByTestId('apply')).toBeDisabled();
  });

  test('contactor ATS needs both interlocks, then the panel is built', async ({ page }) => {
    await choose(page, 'generator', /DHY-8500SE/);
    await page.getByTestId('ats-kind').selectOption('contactor');
    await expect(finding(page, 'NO_MECHANICAL_INTERLOCK')).toBeVisible();
    await expect(finding(page, 'NO_ELECTRICAL_INTERLOCK')).toBeVisible();

    await page.getByTestId('ats-rated').fill('32');
    await page.getByTestId('mech-interlock').check();
    await expect(finding(page, 'NO_MECHANICAL_INTERLOCK')).toHaveCount(0);
    await page.getByTestId('elec-interlock').check();
    await expect(page.getByTestId('power-status')).toHaveAttribute('data-ok', 'true');
    await expect(
      page.getByTestId('components').getByText('Механическая блокировка пары контакторов'),
    ).toBeVisible();

    await page.getByTestId('apply').click();
    await expect(page.getByTestId('applied-link')).toBeVisible();
    await page.getByTestId('applied-link').click();
    await expect(page.getByText('Щит резерва')).toBeVisible();
    await expect(page.getByTestId('device')).toHaveCount(6);
  });

  test('inverter scenario reports autonomy and reacts to the loads', async ({ page }) => {
    await page.getByTestId('scenario').selectOption('grid_inverter');
    await choose(page, 'inverter', /SUN-5K-SG03LP1-EU/);
    await choose(page, 'battery', /US5000/);
    await expect(page.getByTestId('autonomy')).toBeVisible();
    const before = await page.getByTestId('p-backup').innerText();
    expect(before).toContain('3420');
    await expect(finding(page, 'AUTONOMY_LOW')).toBeVisible(); // 1 battery, 4 h target

    // take the air conditioner out of the backup: 3420 -> 1820 W
    await page.getByRole('checkbox', { name: 'Кондиционер' }).uncheck();
    await expect(page.getByTestId('p-backup')).toContainText('1820');
  });
});
