import type { JSX } from 'react';
const SKELETON_GROUPS = [4, 5, 3] as const;

export function MetricsSkeleton(): JSX.Element {
  return (
    <output
      aria-label="Loading runtime metrics"
      aria-live="polite"
      className="block animate-pulse space-y-8"
    >
      {SKELETON_GROUPS.map((tileCount) => (
        <section key={tileCount} aria-hidden="true">
          <div className="h-3 w-24 rounded-sm bg-white/8" />
          <div className="mt-3 flex flex-wrap gap-px border border-(--hairline) bg-(--hairline)">
            {Array.from({ length: tileCount }, (_, tileIndex) => (
              <div
                key={tileIndex}
                className="h-32 min-w-0 basis-56 grow bg-(--surface) p-5"
                data-skeleton-runtime-metric
              >
                <div className="h-2.5 w-20 rounded-sm bg-white/8" />
                <div className="mt-4 h-7 w-28 rounded-sm bg-white/10" />
                <div className="mt-4 h-2.5 w-full rounded-sm bg-white/6" />
                <div className="mt-2 h-2.5 w-4/5 rounded-sm bg-white/6" />
              </div>
            ))}
          </div>
        </section>
      ))}
    </output>
  );
}
