import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

interface Json {
  [k: string]: unknown;
}

async function api(req: APIRequestContext, method: 'get' | 'post', path: string, data?: Json) {
  const csrf = (await req.storageState()).cookies.find((c) => c.name === 'csrftoken')?.value ?? '';
  const res = await req[method](`/api/v1${path}`, {
    data,
    headers: { 'X-CSRFToken': csrf, Referer: 'http://localhost:5173/' },
  });
  expect(res.ok(), `${method} ${path}: ${await res.text()}`).toBeTruthy();
  return (await res.json()) as Json;
}

/** Register a fresh user, create a project with a 2-row panel and two groups. Returns ids. */
async function seed(page: Page) {
  const req = page.request;
  await api(req, 'get', '/auth/csrf/');
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  await api(req, 'post', '/auth/register/', { email, password: 'Pass-12345-xyz' });
  const project = await api(req, 'post', '/projects/', { name: 'E2E' });
  const enclosures = (await api(
    req,
    'get',
    '/catalog/products/?category=enclosure&page_size=100',
  )) as {
    results: { id: number; sku: string; electrical: { rows: number } }[];
  };
  const enc = enclosures.results.find((e) => e.electrical.rows === 2 && e.sku.includes('24'));
  expect(enc).toBeTruthy();
  const panel = await api(req, 'post', `/projects/${project.id}/panels/`, {
    name: 'ГРЩ',
    kind: 'main',
    enclosure: enc?.id,
  });
  await api(req, 'post', `/projects/${project.id}/groups/`, {
    name: 'Кухня розетки',
    power_w: 3000,
    type: 'sockets',
  });
  await api(req, 'post', `/projects/${project.id}/groups/`, {
    name: 'Свет зал',
    power_w: 400,
    type: 'lighting',
  });
  await api(req, 'post', `/projects/${project.id}/groups/autoselect/`);
  return { projectId: project.id as number, panelId: panel.id as number };
}

test.describe('board editor', () => {
  let projectId = 0;
  let panelId = 0;

  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1500, height: 900 });
    ({ projectId, panelId } = await seed(page));
    await page.goto(`/projects/${projectId}/board`);
    await expect(page.getByTestId('panel')).toBeVisible();
    expect(panelId).toBeGreaterThan(0);
  });

  test('drag from palette to rail shows ghost, drops, autosaves and survives reload', async ({
    page,
  }) => {
    await page.getByPlaceholder('Поиск…').fill('C16');
    const item = page.getByTestId('palette-item').filter({ hasText: 'S201' }).first();
    await expect(item).toBeVisible();
    const rail = page.getByTestId('rail').first();
    const r = (await rail.boundingBox())!;
    const a = (await item.boundingBox())!;
    await page.mouse.move(a.x + 20, a.y + 10);
    await page.mouse.down();
    await page.mouse.move(a.x + 40, a.y + 30, { steps: 3 });
    await page.mouse.move(r.x + 36 * 3 + 10, r.y + 60, { steps: 10 });
    await expect(page.getByTestId('ghost')).toHaveAttribute('data-valid', 'true');
    await page.mouse.up();

    await expect(page.getByTestId('device')).toHaveCount(1);
    await expect(page.getByTestId('save-state')).toHaveAttribute('data-state', 'saved', {
      timeout: 10_000,
    });
    await page.reload();
    await expect(page.getByTestId('device')).toHaveCount(1);
  });

  test('collision is flagged invalid and nothing is added', async ({ page }) => {
    await page.getByPlaceholder('Поиск…').fill('C16');
    const item = page.getByTestId('palette-item').filter({ hasText: 'S201' }).first();
    await item.click(); // click-to-add -> first free spot (module 0)
    await expect(page.getByTestId('device')).toHaveCount(1);
    const dev = (await page.getByTestId('device').first().boundingBox())!;
    const a = (await item.boundingBox())!;
    await page.mouse.move(a.x + 20, a.y + 10);
    await page.mouse.down();
    await page.mouse.move(a.x + 40, a.y + 30, { steps: 3 });
    await page.mouse.move(dev.x + dev.width / 2, dev.y + dev.height / 2, { steps: 10 });
    await expect(page.getByTestId('ghost')).toHaveAttribute('data-valid', 'false');
    await page.mouse.up();
    await expect(page.getByTestId('device')).toHaveCount(1);
    await expect(page.getByTestId('toast')).toBeVisible();
  });

  test('group from the unplaced list binds a labelled breaker; BOM updates; trash removes', async ({
    page,
  }) => {
    await expect(page.getByTestId('unplaced-item')).toHaveCount(2);
    const rail = (await page.getByTestId('rail').first().boundingBox())!;
    const g = page.getByTestId('unplaced-item').first();
    const a = (await g.boundingBox())!;
    await page.mouse.move(a.x + 10, a.y + 8);
    await page.mouse.down();
    await page.mouse.move(a.x + 30, a.y + 20, { steps: 3 });
    await page.mouse.move(rail.x + 100, rail.y + 60, { steps: 10 });
    await page.mouse.up();
    await expect(page.getByTestId('device')).toHaveCount(1);
    await expect(page.getByTestId('device-label')).toBeVisible();
    await expect(page.getByTestId('unplaced-item')).toHaveCount(1);
    await expect(page.getByTestId('bom-total')).not.toHaveText(/^0[,.]00/);

    // drag the device to the trash
    const dev = (await page.getByTestId('device').first().boundingBox())!;
    const trash = (await page.getByTestId('trash').boundingBox())!;
    await page.mouse.move(dev.x + dev.width / 2, dev.y + dev.height / 2);
    await page.mouse.down();
    await page.mouse.move(dev.x + 30, dev.y + 30, { steps: 3 });
    await page.mouse.move(trash.x + trash.width / 2, trash.y + trash.height / 2, { steps: 10 });
    await page.mouse.up();
    await expect(page.getByTestId('device')).toHaveCount(0);
    await expect(page.getByTestId('unplaced-item')).toHaveCount(2);
  });

  test('move between rails, undo/redo and multi-select copy/paste', async ({ page }) => {
    await page.getByPlaceholder('Поиск…').fill('C16');
    const item = page.getByTestId('palette-item').filter({ hasText: 'S201' }).first();
    await item.click();
    await item.click();
    await expect(page.getByTestId('device')).toHaveCount(2);

    const rails = page.getByTestId('rail');
    const r2 = (await rails.nth(1).boundingBox())!;
    const id0 = (await page.getByTestId('device').first().getAttribute('data-device-id'))!;
    const dev0 = page.locator(`[data-device-id="${id0}"]`);
    const d0 = (await dev0.boundingBox())!;
    await page.mouse.move(d0.x + d0.width / 2, d0.y + d0.height / 2);
    await page.mouse.down();
    await page.mouse.move(d0.x + 30, d0.y + 30, { steps: 3 });
    await page.mouse.move(r2.x + 200, r2.y + 60, { steps: 10 });
    await page.mouse.up();
    const moved = (await dev0.boundingBox())!;
    expect(Math.abs(moved.y - r2.y)).toBeLessThan(40);

    await page.keyboard.press('Control+z');
    const back = (await dev0.boundingBox())!;
    expect(Math.abs(back.y - d0.y)).toBeLessThan(2);
    await page.keyboard.press('Control+Shift+z');

    // select both with shift-click, copy + paste -> 4 devices
    await page.getByTestId('device').nth(0).click();
    await page
      .getByTestId('device')
      .nth(1)
      .click({ modifiers: ['Shift'] });
    await page.keyboard.press('Control+c');
    await page.keyboard.press('Control+v');
    await expect(page.getByTestId('device')).toHaveCount(4);
  });

  test('zoom keeps drop positions correct', async ({ page }) => {
    await page.getByRole('button', { name: 'Увеличить' }).click();
    await page.getByRole('button', { name: 'Увеличить' }).click();
    await expect(page.getByTestId('zoom')).toHaveText('144%');
    await page.getByPlaceholder('Поиск…').fill('C16');
    const item = page.getByTestId('palette-item').filter({ hasText: 'S201' }).first();
    const rail = (await page.getByTestId('rail').first().boundingBox())!;
    const a = (await item.boundingBox())!;
    await page.mouse.move(a.x + 20, a.y + 10);
    await page.mouse.down();
    await page.mouse.move(a.x + 40, a.y + 30, { steps: 3 });
    // pointer 5.5 modules (at 144%) from the rail's left edge => device centred there
    await page.mouse.move(rail.x + 36 * 1.44 * 5.5, rail.y + 60, { steps: 10 });
    await page.mouse.up();
    const dev = (await page.getByTestId('device').first().boundingBox())!;
    const startModules = (dev.x - rail.x) / (36 * 1.44);
    expect(Math.round(startModules)).toBeGreaterThanOrEqual(4);
    expect(Math.round(startModules)).toBeLessThanOrEqual(6);
  });

  test('autolayout fills the board with the groups, then manual edit works', async ({ page }) => {
    await page.getByRole('button', { name: 'Автокомпоновка' }).click();
    await page.getByRole('button', { name: 'Выполнить' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0, { timeout: 15_000 });
    expect(await page.getByTestId('device').count()).toBeGreaterThan(3);
    await expect(page.getByTestId('unplaced-item')).toHaveCount(0);
    await page.getByTestId('device').first().click();
    await page.keyboard.press('Delete');
    await expect(page.getByTestId('save-state')).toHaveAttribute('data-state', 'saved', {
      timeout: 10_000,
    });
  });

  test('single-line diagram mirrors the board both ways', async ({ page }) => {
    await page.getByRole('button', { name: 'Автокомпоновка' }).click();
    await page.getByRole('button', { name: 'Выполнить' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0, { timeout: 15_000 });
    const devices = await page.getByTestId('device').count();
    expect(devices).toBeGreaterThan(3);

    await page.getByTestId('tab-diagram').click();
    // feeder and bus are extra nodes
    await expect(page.getByTestId('diagram-node')).toHaveCount(devices + 2);
    await page.screenshot({ path: 'test-results/diagram.png' });

    // select on the diagram -> selected on the board
    const node = page.getByTestId('diagram-node').filter({ hasText: 'QF1' }).first();
    const id = (await node.getAttribute('data-node-id'))!;
    await node.click();
    await page.getByTestId('tab-board').click();
    await expect(page.locator(`[data-device-id="${id}"]`)).toHaveClass(/ring-blue-600/);

    // delete on the board -> node disappears from the diagram
    await page.keyboard.press('Delete');
    await page.getByTestId('tab-diagram').click();
    await expect(page.getByTestId('diagram-node')).toHaveCount(devices + 1);

    // delete from the diagram view -> device disappears on the board
    await page.getByTestId('diagram-node').filter({ hasText: 'QF' }).first().click();
    await page.keyboard.press('Delete');
    await expect(page.getByTestId('diagram-node')).toHaveCount(devices);
    await page.getByTestId('tab-board').click();
    await expect(page.getByTestId('device')).toHaveCount(devices - 2);
  });

  test('mobile viewport is read-only', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 800 });
    await expect(page.getByText('Просмотр', { exact: false })).toBeVisible();
    await expect(page.getByTestId('palette-item')).toHaveCount(0);
  });
});
