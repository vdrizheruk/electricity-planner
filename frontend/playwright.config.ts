import { defineConfig } from '@playwright/test';

const executablePath = process.env.PW_CHROMIUM_PATH || undefined;

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    trace: 'off',
    launchOptions: { executablePath },
  },
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : [
        {
          command: 'python manage.py runserver 8000 --noreload',
          cwd: '../backend',
          // every test registers a fresh user: lift the rate limits of the throwaway e2e server
          env: {
            THROTTLE_ANON: '100000/min',
            THROTTLE_USER: '100000/min',
            THROTTLE_AUTH: '100000/min',
          },
          url: 'http://localhost:8000/healthz',
          reuseExistingServer: true,
          timeout: 60_000,
        },
        {
          command: 'npm run dev -- --host localhost',
          url: 'http://localhost:5173',
          reuseExistingServer: true,
          timeout: 60_000,
        },
      ],
});
