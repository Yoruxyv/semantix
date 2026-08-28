import type { JSX } from 'react';

const READING_ROWS = [0, 1, 2, 3, 4, 5] as const;

export function CacheReadingsSkeleton(): JSX.Element {
  return (
    <output
      aria-label="Loading cache readings"
      aria-live="polite"
      className="block animate-pulse"
    >
      <span className="sr-only">
        Loading cache statistics and similarity threshold.
      </span>
      <span
        aria-hidden="true"
        className="grid grid-cols-1 gap-14 min-[760px]:grid-cols-[minmax(280px,3fr)_minmax(0,2fr)]"
      >
        <span className="block">
          <span className="block h-7 w-40 bg-[rgba(234,230,221,0.08)]" />
          <span className="mt-4 block h-3 w-64 max-w-full bg-[rgba(234,230,221,0.05)]" />
          <span className="mt-7 block border-t border-(--hairline)">
            {READING_ROWS.map((row) => (
              <span
                className="flex items-center justify-between border-b border-(--hairline) py-4"
                key={row}
                data-skeleton-reading
              >
                <span className="h-2.5 w-40 bg-[rgba(234,230,221,0.06)]" />
                <span className="h-4 w-16 bg-[rgba(91,156,148,0.12)]" />
              </span>
            ))}
          </span>
        </span>
        <span className="block">
          <span className="block h-7 w-56 max-w-full bg-[rgba(234,230,221,0.08)]" />
          <span className="mt-4 block h-3 w-72 max-w-full bg-[rgba(234,230,221,0.05)]" />
          <span className="mt-7 grid grid-cols-3 gap-px bg-(--hairline)">
            {[0, 1, 2].map((stat) => (
              <span className="block h-12 bg-(--ink) p-3" key={stat} />
            ))}
          </span>
          <span
            className="mt-5 block h-48 w-full border border-(--hairline) bg-[rgba(234,230,221,0.03)]"
            data-skeleton-similarity-plot
          />
          <span className="mt-5 block border-t border-(--hairline) pt-5">
            <span className="block h-2.5 w-32 bg-[rgba(234,230,221,0.06)]" />
            <span className="mt-4 flex items-center gap-4">
              <span className="block h-1.5 flex-1 bg-[rgba(212,161,90,0.12)]" />
              <span className="block h-10 w-24 border border-(--hairline) bg-(--surface)" />
            </span>
          </span>
        </span>
      </span>
    </output>
  );
}
