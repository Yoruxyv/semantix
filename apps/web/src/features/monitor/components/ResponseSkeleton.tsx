import type { JSX } from 'react';

const EVIDENCE_ITEMS = [0, 1, 2, 3, 4, 5, 6] as const;

export function ResponseSkeleton(): JSX.Element {
  return (
    <output
      aria-label="Loading query response"
      aria-live="polite"
      className="block animate-pulse border-y border-l-2 border-(--hairline) border-l-(--gold) bg-(--surface) px-4 py-5 sm:px-6"
    >
      <span className="sr-only">
        Embedding the prompt and checking the semantic cache.
      </span>
      <span className="flex items-center justify-between gap-6 border-b border-(--hairline) pb-4">
        <span className="h-5 w-36 bg-[rgba(234,230,221,0.08)]" />
        <span className="h-3 w-20 bg-[rgba(212,161,90,0.18)]" />
      </span>
      <span className="mt-5 block h-3 w-full bg-[rgba(234,230,221,0.06)]" />
      <span className="mt-3 block h-3 w-11/12 bg-[rgba(234,230,221,0.06)]" />
      <span className="mt-3 block h-3 w-3/5 bg-[rgba(234,230,221,0.06)]" />
      <span className="mt-6 block border-t border-(--hairline) pt-4">
        <span className="block h-2.5 w-28 bg-[rgba(234,230,221,0.05)]" />
        <span className="mt-3 block h-3 w-full bg-[rgba(234,230,221,0.05)]" />
        <span className="mt-2 block h-3 w-4/5 bg-[rgba(234,230,221,0.05)]" />
      </span>
      <span className="mt-4 grid grid-cols-1 border-t border-(--hairline) min-[520px]:grid-cols-2 min-[860px]:grid-cols-4">
        {EVIDENCE_ITEMS.map((item) => (
          <span
            className={`min-h-16 border-b border-(--hairline) py-3 ${
              item === 4 ? 'min-[520px]:col-span-2 min-[860px]:col-span-2' : ''
            }`}
            data-skeleton-evidence-metric
            key={item}
          >
            <span className="block h-2 w-16 bg-[rgba(234,230,221,0.05)]" />
            <span className="mt-2 block h-3 w-20 max-w-4/5 bg-[rgba(91,156,148,0.12)]" />
          </span>
        ))}
      </span>
    </output>
  );
}
