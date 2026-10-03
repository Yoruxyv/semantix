import { useRef, type ChangeEvent, type JSX } from 'react';

import { Button } from '@/shared/components/ui';
import { formatCount } from '@/shared/lib/formatters';
import {
  EVALUATION_IMPORT_FILE_MAX_BYTES,
  type BenchmarkController,
} from '@/features/benchmark/hooks/useBenchmark';

interface BenchmarkDatasetImportProps {
  controller: BenchmarkController;
}

export function BenchmarkDatasetImport({
  controller,
}: Readonly<BenchmarkDatasetImportProps>): JSX.Element {
  const input = useRef<HTMLInputElement>(null);
  const {
    importError,
    importFileName,
    importIssues,
    isRunning,
    isValidatingImport,
    preview,
  } = controller;

  function selectFile(event: ChangeEvent<HTMLInputElement>): void {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (file !== undefined) {
      void controller.selectImportFile(file);
    }
  }

  function removeFile(): void {
    controller.removeImport();
    input.current?.focus();
  }

  return (
    <section
      aria-labelledby="evaluation-import-heading"
      className="border border-(--hairline) bg-[rgba(234,230,221,0.025)] p-4 sm:p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="ui-label text-(--text-muted)" id="evaluation-import-heading">
            Session-local JSON dataset
          </h2>
          <p
            className="font-data mt-2 max-w-3xl text-[10px]/5 text-(--text-faint)"
            id="evaluation-import-guidance"
          >
            Choose one schema version 1 JSON file. The browser limit is{' '}
            {formatCount(EVALUATION_IMPORT_FILE_MAX_BYTES)} bytes; the server also
            enforces decoded-content, case-count, and workload limits. The file stays in
            this page&apos;s memory and is cleared on removal, reload, sign-out, or
            principal change.
          </p>
        </div>

        {importFileName !== null && (
          <Button
            disabled={isRunning}
            size="compact"
            variant="secondary"
            onClick={removeFile}
          >
            Remove imported dataset
          </Button>
        )}
      </div>

      <label className="mt-4 block">
        <span className="ui-label text-(--text-muted)">JSON dataset file</span>
        <input
          ref={input}
          accept=".json,application/json"
          aria-describedby="evaluation-import-guidance"
          className="font-data mt-2 block min-h-11 w-full max-w-full border border-(--hairline) bg-(--surface) px-3 py-2 text-xs text-(--text-soft) file:mr-4 file:border-0 file:bg-(--gold) file:px-3 file:py-2 file:text-(--ink) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--gold) disabled:opacity-50"
          disabled={isRunning || isValidatingImport}
          type="file"
          onChange={selectFile}
        />
      </label>

      {importFileName !== null && (
        <p className="font-data mt-3 wrap-break-word text-[10px]/5 text-(--text-muted)">
          Selected: {importFileName}
        </p>
      )}

      {isValidatingImport && (
        <output
          aria-live="polite"
          className="font-data mt-3 block text-[10px]/5 text-(--gold)"
        >
          Validating imported dataset without provider calls...
        </output>
      )}

      {importError !== null && (
        <div className="mt-4 border-l-2 border-(--coral) pl-4" role="alert">
          <p className="ui-label text-(--coral-text)">Dataset validation failed</p>
          <p className="font-data mt-2 text-[10px]/5 text-(--text-soft)">
            {importError}
          </p>
          {importIssues.length > 0 && (
            <ul className="font-data mt-3 grid gap-2 text-[10px]/5 text-(--text-muted)">
              {importIssues.map((issue, index) => (
                <li key={`${issue.pointer}-${issue.code}-${index}`}>
                  <span className="text-(--coral-text)">{issue.code}</span>
                  {' — '}
                  {issue.detail} Reference: {issue.pointer}
                  {issue.case_id === undefined ? '' : `; case ${issue.case_id}`}
                  {issue.case_index === undefined ? '' : `; index ${issue.case_index}`}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {preview !== null && (
        <section
          aria-labelledby="evaluation-preview-heading"
          className="mt-5 border-t border-(--hairline) pt-4"
        >
          <p className="ui-label text-(--teal)" id="evaluation-preview-heading">
            Validated preview
          </p>
          <h3 className="font-display mt-2 wrap-break-word text-xl italic">
            {preview.name}
          </h3>
          {preview.description !== null && (
            <p className="mt-2 whitespace-pre-wrap wrap-break-word text-sm/6 text-(--text-soft)">
              {preview.description}
            </p>
          )}
          <dl className="font-data mt-4 grid gap-3 text-[10px]/5 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-(--text-faint)">Schema / digest</dt>
              <dd className="mt-1 break-all text-(--text-soft)">
                v{preview.schema_version} · {preview.digest}
              </dd>
            </div>
            <div>
              <dt className="text-(--text-faint)">Cases</dt>
              <dd className="mt-1 text-(--text-soft)">
                {formatCount(preview.case_count)} · {formatCount(preview.expected_hits)}{' '}
                expected hits · {formatCount(preview.expected_misses)} expected misses
              </dd>
            </div>
            <div>
              <dt className="text-(--text-faint)">Decoded content</dt>
              <dd className="mt-1 text-(--text-soft)">
                {formatCount(preview.decoded_bytes)} /{' '}
                {formatCount(preview.limits.max_decoded_bytes)} bytes
              </dd>
            </div>
            <div>
              <dt className="text-(--text-faint)">Bounded review workload</dt>
              <dd className="mt-1 text-(--text-soft)">
                {formatCount(preview.query_executions)} queries ·{' '}
                {formatCount(preview.threshold_projection_evaluations)} threshold
                projections
              </dd>
            </div>
          </dl>
          <p className="font-data mt-4 text-[10px]/5 text-(--text-muted)">
            Validation made {preview.provider_calls_made} provider calls. Execution may
            send imported prompts outside this system and make at most{' '}
            {formatCount(preview.maximum_provider_calls)} generation calls.
          </p>
          {preview.warnings.length > 0 && (
            <ul className="font-data mt-3 grid gap-2 text-[10px]/5 text-(--gold)">
              {preview.warnings.map((warning) => (
                <li key={warning.code}>
                  {warning.detail} ({formatCount(warning.count)})
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </section>
  );
}
