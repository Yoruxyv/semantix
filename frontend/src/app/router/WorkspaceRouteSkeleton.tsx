import type { JSX } from 'react';

import { APP_PATHS } from '../navigation/navigationConfig';

type WorkspaceKind = 'benchmark' | 'cache' | 'monitor' | 'observability';

interface HeaderSkeletonProps {
  action?: boolean;
  large?: boolean;
}

interface WorkspaceRouteSkeletonProps {
  pathname: string;
}

const BENCHMARK_CONTROLS = [0, 1, 2, 3, 4, 5] as const;
const CACHE_CONTROLS = [0, 1, 2] as const;
const CACHE_ENTRIES = [0, 1] as const;
const CACHE_ENTRY_METRICS = [0, 1, 2, 3, 4, 5] as const;
const OBSERVABILITY_GROUPS = [4, 5, 3] as const;

function kindForPath(pathname: string): WorkspaceKind {
  if (
    pathname.startsWith(APP_PATHS.evaluations) ||
    pathname.startsWith(APP_PATHS.benchmarks)
  ) {
    return 'benchmark';
  }
  if (pathname.startsWith(APP_PATHS.cache)) {
    return 'cache';
  }
  if (pathname.startsWith(APP_PATHS.observability)) {
    return 'observability';
  }
  return 'monitor';
}

function HeaderSkeleton({
  action = false,
  large = false,
}: Readonly<HeaderSkeletonProps>): JSX.Element {
  return (
    <span className="flex flex-wrap items-end justify-between gap-5">
      <span className="block min-w-0 flex-1">
        <span className="block h-2.5 w-28 bg-[rgba(212,161,90,0.16)]" />
        <span
          className={`${large ? 'h-12 w-64' : 'h-9 w-56'} mt-3 block max-w-4/5 bg-[rgba(234,230,221,0.09)]`}
        />
        <span className="mt-4 block h-3 w-full max-w-2xl bg-[rgba(234,230,221,0.05)]" />
        <span className="mt-2 block h-3 w-4/5 max-w-xl bg-[rgba(234,230,221,0.05)]" />
      </span>
      {action && (
        <span className="block h-11 w-36 border border-(--hairline) bg-(--surface)" />
      )}
    </span>
  );
}

function MonitorSkeleton(): JSX.Element {
  return (
    <span className="mt-6 block" data-workspace-skeleton="monitor">
      <HeaderSkeleton />
      <span className="mt-8 block">
        <span className="flex items-center justify-between gap-5">
          <span className="block h-2.5 w-24 bg-[rgba(234,230,221,0.07)]" />
          <span className="block h-2.5 w-28 bg-[rgba(234,230,221,0.05)]" />
        </span>
        <span
          className="mt-3 block h-48 border border-(--hairline) bg-(--surface)"
          data-skeleton-query-input
        />
        <span className="mt-3 flex items-center justify-between gap-5">
          <span className="block h-2.5 w-72 max-w-3/5 bg-[rgba(234,230,221,0.05)]" />
          <span className="block h-2.5 w-16 bg-[rgba(234,230,221,0.05)]" />
        </span>
        <span className="mt-7 flex flex-wrap items-end justify-between gap-6">
          <span className="block space-y-3">
            <span className="block h-2.5 w-28 bg-[rgba(234,230,221,0.06)]" />
            <span className="block h-3 w-72 max-w-full bg-[rgba(91,156,148,0.1)]" />
            <span className="block h-3 w-64 max-w-full bg-[rgba(91,156,148,0.1)]" />
          </span>
          <span className="block h-14 w-40 bg-[rgba(212,161,90,0.16)]" />
        </span>
      </span>
    </span>
  );
}

function CacheEntrySkeleton(): JSX.Element {
  return (
    <span className="block border-t border-(--hairline) py-5" data-skeleton-route-entry>
      <span className="flex items-start justify-between gap-4">
        <span className="block min-w-0 flex-1">
          <span className="block h-2.5 w-56 max-w-3/5 bg-[rgba(91,156,148,0.1)]" />
          <span className="mt-3 block h-4 w-80 max-w-4/5 bg-[rgba(234,230,221,0.08)]" />
        </span>
        <span className="block h-8 w-14 bg-[rgba(194,96,74,0.08)]" />
      </span>
      <span className="mt-4 block h-3 w-full bg-[rgba(234,230,221,0.05)]" />
      <span className="mt-2 block h-3 w-4/5 bg-[rgba(234,230,221,0.05)]" />
      <span className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 min-[720px]:grid-cols-3">
        {CACHE_ENTRY_METRICS.map((metric) => (
          <span className="block" key={metric}>
            <span className="block h-2 w-16 bg-[rgba(234,230,221,0.05)]" />
            <span className="mt-2 block h-3 w-24 bg-[rgba(234,230,221,0.07)]" />
          </span>
        ))}
      </span>
    </span>
  );
}

function CacheSkeleton(): JSX.Element {
  return (
    <span className="mt-6 block" data-workspace-skeleton="cache">
      <HeaderSkeleton />
      <span className="mt-9 block border-t border-(--hairline) pt-8">
        <span className="flex flex-wrap items-end justify-between gap-5">
          <span className="block">
            <span className="block h-7 w-40 bg-[rgba(234,230,221,0.08)]" />
            <span className="mt-3 block h-2.5 w-64 bg-[rgba(234,230,221,0.05)]" />
          </span>
          <span className="flex gap-3">
            <span className="block h-9 w-20 border border-(--hairline) bg-(--surface)" />
            <span className="block h-9 w-32 border border-(--hairline) bg-(--surface)" />
          </span>
        </span>
        <span className="mt-7 grid gap-5 min-[900px]:grid-cols-[minmax(0,1fr)_minmax(180px,0.6fr)_220px]">
          {CACHE_CONTROLS.map((control) => (
            <span className="block" data-skeleton-route-control key={control}>
              <span className="block h-2.5 w-28 bg-[rgba(234,230,221,0.06)]" />
              <span className="mt-3 block h-10 border border-(--hairline) bg-(--surface)" />
            </span>
          ))}
        </span>
        <span className="mt-7 block">
          {CACHE_ENTRIES.map((entry) => (
            <CacheEntrySkeleton key={entry} />
          ))}
        </span>
      </span>
    </span>
  );
}

function BenchmarkControlSkeleton({
  control,
}: Readonly<{ control: number }>): JSX.Element {
  if (control === 5) {
    return (
      <span className="flex flex-col justify-between gap-4" data-skeleton-route-control>
        <span className="flex items-center gap-2">
          <span className="block size-4 bg-[rgba(234,230,221,0.08)]" />
          <span className="block h-2.5 w-48 bg-[rgba(234,230,221,0.06)]" />
        </span>
        <span className="block h-11 bg-[rgba(212,161,90,0.14)]" />
      </span>
    );
  }

  return (
    <span className="block" data-skeleton-route-control>
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
}

function BenchmarkSkeleton(): JSX.Element {
  return (
    <span className="mt-6 block" data-workspace-skeleton="benchmark">
      <HeaderSkeleton />
      <span className="mt-7 grid gap-5 border-y border-(--hairline) py-6 md:grid-cols-3">
        {BENCHMARK_CONTROLS.map((control) => (
          <BenchmarkControlSkeleton control={control} key={control} />
        ))}
      </span>
    </span>
  );
}

function ObservabilitySkeleton(): JSX.Element {
  return (
    <span className="mt-6 block" data-workspace-skeleton="observability">
      <HeaderSkeleton action large />
      <span className="mt-8 block space-y-8">
        {OBSERVABILITY_GROUPS.map((tileCount) => (
          <span className="block" key={tileCount}>
            <span className="block h-2.5 w-24 bg-[rgba(234,230,221,0.06)]" />
            <span className="mt-3 flex flex-wrap gap-px border border-(--hairline) bg-(--hairline)">
              {Array.from({ length: tileCount }, (_, tile) => (
                <span
                  className="block h-32 min-w-0 basis-56 grow bg-(--surface) p-5"
                  data-skeleton-route-metric
                  key={tile}
                >
                  <span className="block h-2.5 w-20 bg-[rgba(234,230,221,0.06)]" />
                  <span className="mt-4 block h-7 w-28 bg-[rgba(234,230,221,0.09)]" />
                  <span className="mt-4 block h-2.5 w-full bg-[rgba(234,230,221,0.05)]" />
                  <span className="mt-2 block h-2.5 w-4/5 bg-[rgba(234,230,221,0.05)]" />
                </span>
              ))}
            </span>
          </span>
        ))}
      </span>
    </span>
  );
}

export function WorkspaceRouteSkeleton({
  pathname,
}: Readonly<WorkspaceRouteSkeletonProps>): JSX.Element {
  const kind = kindForPath(pathname);

  return (
    <span aria-hidden="true" className="block">
      {kind === 'benchmark' && <BenchmarkSkeleton />}
      {kind === 'cache' && <CacheSkeleton />}
      {kind === 'monitor' && <MonitorSkeleton />}
      {kind === 'observability' && <ObservabilitySkeleton />}
    </span>
  );
}
