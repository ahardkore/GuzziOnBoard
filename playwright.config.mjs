import { defineConfig, devices } from '@playwright/test';
import serverlessChromium, { inflate, setupLambdaEnvironment } from '@sparticuz/chromium';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';

// The npm-packaged headless binary makes the browser gate reproducible on
// minimal Linux CI hosts where Playwright's CDN or NSS packages are absent.
// Other platforms use the normal `npx playwright install chromium` browser.
let linuxLaunch = {};
if (process.platform === 'linux') {
  const packageBuild = dirname(fileURLToPath(import.meta.resolve('@sparticuz/chromium')));
  await inflate(join(packageBuild, '..', 'bin', 'al2023.tar.br'));
  setupLambdaEnvironment(join(tmpdir(), 'al2023', 'lib'));
  linuxLaunch = {
    executablePath: await serverlessChromium.executablePath(),
    args: serverlessChromium.args.filter((argument) => argument !== '--single-process'),
  };
}

export default defineConfig({
  testDir: './tests/browser',
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    permissions: ['clipboard-read', 'clipboard-write'],
    launchOptions: linuxLaunch,
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command: 'python3 -m http.server 4173 --bind 0.0.0.0 --directory .',
    url: 'http://127.0.0.1:4173/web/index.html',
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
