import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdirSync, readFileSync, rmSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { LIGHTHOUSE_BUDGET, main as checkBudget } from './check-lighthouse-budget.js';

const frontendDirectory = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const reportDirectory = resolve(frontendDirectory, 'lighthouse-reports');
const previewUrl = 'http://127.0.0.1:4173/';
const viteCli = resolve(frontendDirectory, 'node_modules/vite/bin/vite.js');
const lighthouseCli = resolve(
  frontendDirectory,
  'node_modules/lighthouse/cli/index.js',
);

const delay = (milliseconds) =>
  new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));

const runNode = (args, { allowFailure = false } = {}) =>
  new Promise((resolveRun, rejectRun) => {
    const child = spawn(process.execPath, args, {
      cwd: frontendDirectory,
      stdio: 'inherit',
    });

    child.once('error', rejectRun);
    child.once('exit', (code, signal) => {
      if (code === 0 || allowFailure) {
        resolveRun(code ?? 1);
        return;
      }

      const status = signal ? `signal ${signal}` : `code ${code}`;
      rejectRun(new Error(`${args[0]} exited with ${status}.`));
    });
  });

const waitForPreview = async (preview) => {
  let previewError;
  preview.once('error', (error) => {
    previewError = error;
  });

  for (let attempt = 1; attempt <= 30; attempt += 1) {
    if (previewError) {
      throw previewError;
    }

    if (preview.exitCode !== null) {
      throw new Error(`Vite preview exited with code ${preview.exitCode}.`);
    }

    try {
      const response = await fetch(previewUrl);
      if (response.ok) {
        return;
      }
    } catch {
      // Preview is still starting.
    }

    await delay(1000);
  }

  throw new Error(`Vite preview did not become reachable at ${previewUrl}.`);
};

const stopPreview = async (preview) => {
  if (!preview || preview.exitCode !== null) {
    return;
  }

  const exited = once(preview, 'exit');
  preview.kill();
  await Promise.race([exited, delay(3000)]);

  if (preview.exitCode === null) {
    preview.kill('SIGKILL');
  }
};

const hasCompleteReport = (path) => {
  try {
    const report = JSON.parse(readFileSync(path, 'utf8'));
    return ['performance', 'accessibility', 'best-practices', 'seo'].every(
      (category) => typeof report.categories?.[category]?.score === 'number',
    );
  } catch {
    return false;
  }
};

const runAudit = async (profile, run) => {
  const outputPath = resolve(reportDirectory, `${profile}-${run}.json`);
  const args = [lighthouseCli, previewUrl];

  if (profile === 'desktop') {
    args.push('--preset=desktop');
  }

  args.push(
    '--output=json',
    `--output-path=${outputPath}`,
    '--chrome-flags=--headless --no-sandbox',
    '--quiet',
  );

  console.log(
    `\n${profile === 'desktop' ? 'Desktop' : 'Mobile'} ${run}/${LIGHTHOUSE_BUDGET.runCount}`,
  );
  const exitCode = await runNode(args, { allowFailure: true });

  if (exitCode !== 0 && !hasCompleteReport(outputPath)) {
    throw new Error(`Lighthouse ${profile} run ${run} failed.`);
  }

  if (exitCode !== 0) {
    console.warn(
      'Lighthouse returned a cleanup error after writing a complete report; continuing.',
    );
  }
};

let preview;

const handleSignal = (exitCode) => {
  stopPreview(preview).finally(() => {
    process.exit(exitCode);
  });
};

const handleInterrupt = () => handleSignal(130);
const handleTermination = () => handleSignal(143);

process.once('SIGINT', handleInterrupt);
process.once('SIGTERM', handleTermination);

let exitCode = 1;

try {
  console.log('Building Semantix frontend...');
  await runNode([viteCli, 'build']);

  preview = spawn(
    process.execPath,
    [viteCli, 'preview', '--host', '127.0.0.1', '--port', '4173', '--strictPort'],
    { cwd: frontendDirectory, stdio: 'inherit' },
  );
  await waitForPreview(preview);

  if (dirname(reportDirectory) !== frontendDirectory) {
    throw new Error('Refusing to clean an unexpected Lighthouse report path.');
  }
  rmSync(reportDirectory, { recursive: true, force: true });
  mkdirSync(reportDirectory);

  await runAudit('desktop', 'warm-up');
  rmSync(resolve(reportDirectory, 'desktop-warm-up.json'));

  for (const profile of ['desktop', 'mobile']) {
    for (let run = 1; run <= LIGHTHOUSE_BUDGET.runCount; run += 1) {
      await runAudit(profile, run);
    }
  }

  exitCode = checkBudget([reportDirectory]);
} catch (error) {
  console.error(`\nSemantix Lighthouse run failed:\n${error.message}`);
} finally {
  process.removeListener('SIGINT', handleInterrupt);
  process.removeListener('SIGTERM', handleTermination);
  await stopPreview(preview);
}

process.exitCode = exitCode;
