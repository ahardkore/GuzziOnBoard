import { defineConfig, devices } from '@playwright/test';
import serverlessChromium, { inflate, setupLambdaEnvironment } from '@sparticuz/chromium';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';

// The desktop host gate: the UI as the *desktop application* serves it.
//
// The other spec (map-editor.spec.mjs, under playwright.config.mjs) runs the
// page on a plain static server, which is the hosted-demo path: demo-api.js
// answers /api inside the page. This one runs the page behind
// `guzzionboard-desktop --no-window`, so the real Python API answers, the
// server injects the desktop bridge, and saving/printing go through a real
// host. Both matter: the UI has to work in a tab, and it has to work as an
// installed application.

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

const PORT = 4174;

export default defineConfig({
  testDir: './tests/browser',
  testMatch: /desktop-host\.spec\.mjs/,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: linuxLaunch,
    ...devices['Desktop Chrome'],
  },
  webServer: {
    // A real desktop launch: loopback server, desktop bridge, no window (the
    // tests drive the page in Chromium instead). A throwaway data root and
    // export folder keep the run away from the user's real files.
    command:
      'GUZZIONBOARD_HOME=.desktop-test-data python3 -m guzzionboard.desktop ' +
      `--no-window --no-record --port ${PORT} --export-dir .desktop-test-data/exports`,
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: 'pipe',
  },
});
