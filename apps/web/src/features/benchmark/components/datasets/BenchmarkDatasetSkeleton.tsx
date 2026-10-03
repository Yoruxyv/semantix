import type { JSX } from 'react';

const CONTROL_SKELETONS = [0, 1, 2, 3, 4, 5] as const;

export function BenchmarkDatasetSkeleton(): JSX.Element {
  return (
    <output
      aria-label="Loading benchmark datasets"
      aria-live="polite"
      className="block animate-pulse border-y border-(--hairline) py-6"
    >
      <span className="sr-only">Loading the benchmark dataset catalog.</span>
      <span aria-hidden="true" className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {CONTROL_SKELETONS.map((control) => {
          if (control === 5) {
            return (
              <span
                className="flex flex-col justify-between gap-4"
                data-skeleton-control
                key={control}
              >
                <span className="flex items-center gap-2">
                  <span className="block size-4 bg-[rgba(234,230,221,0.08)]" />
                  <span className="block h-2.5 w-48 bg-[rgba(234,230,221,0.06)]" />
                </span>
                <span className="block h-11 bg-[rgba(212,161,90,0.14)]" />
              </span>
            );
          }

          return (
            <span className="block" data-skeleton-control key={control}>
              <span className="block h-2.5 w-28 bg-[rgba(234,230,221,0.06)]" />
              {control === 1 ? (
                <span className="mt-4 flex items-center gap-3">
                  <span className="block h-1.5 flex-1 bg-[rgba(212,161,90,0.12)]" />
                  <span className="block h-4 w-10 bg-[rgba(234,230,221,0.08)]" />
                </span>
              ) : (
                <span className="mt-3 block h-10 border border-(--hairline) bg-(--surface)" />
              )}
            </span>
          );
        })}
      </span>
    </output>
  );
}
