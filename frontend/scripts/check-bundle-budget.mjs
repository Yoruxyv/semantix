import { gzipSync } from 'node:zlib';
import { readdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const RAW_BUDGET_BYTES = 450 * 1024;
const GZIP_BUDGET_BYTES = 135 * 1024;
const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const assetsDirectory = path.resolve(scriptDirectory, '../dist/assets');

const formatKibibytes = (bytes) => `${(bytes / 1024).toFixed(2)} KiB`;

const assetNames = (await readdir(assetsDirectory)).filter((name) =>
  name.endsWith('.js'),
);

if (assetNames.length === 0) {
  throw new Error(`No JavaScript bundles were found in ${assetsDirectory}`);
}

const bundles = await Promise.all(
  assetNames.map(async (name) => {
    const content = await readFile(path.join(assetsDirectory, name));
    return {
      gzipBytes: gzipSync(content).byteLength,
      name,
      rawBytes: content.byteLength,
    };
  }),
);

const largestRaw = bundles.reduce((largest, bundle) =>
  bundle.rawBytes > largest.rawBytes ? bundle : largest,
);
const largestGzip = bundles.reduce((largest, bundle) =>
  bundle.gzipBytes > largest.gzipBytes ? bundle : largest,
);

console.log(
  [
    `Largest raw JavaScript chunk: ${largestRaw.name}`,
    formatKibibytes(largestRaw.rawBytes),
    `(budget ${formatKibibytes(RAW_BUDGET_BYTES)})`,
  ].join(' '),
);
console.log(
  [
    `Largest gzip JavaScript chunk: ${largestGzip.name}`,
    formatKibibytes(largestGzip.gzipBytes),
    `(budget ${formatKibibytes(GZIP_BUDGET_BYTES)})`,
  ].join(' '),
);

const warnings = [];
if (largestRaw.rawBytes > RAW_BUDGET_BYTES) {
  warnings.push('raw JavaScript chunk budget exceeded');
}
if (largestGzip.gzipBytes > GZIP_BUDGET_BYTES) {
  warnings.push('gzip JavaScript chunk budget exceeded');
}

if (warnings.length > 0) {
  console.warn(
    `::warning title=Frontend bundle budget::${warnings.join('; ')}. ` +
      'Review bundle growth; this warning does not fail CI.',
  );
} else {
  console.log('Frontend bundle sizes are within the warning budget.');
}
