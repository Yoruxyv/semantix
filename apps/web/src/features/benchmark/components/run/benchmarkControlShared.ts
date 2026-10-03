import type {
  BenchmarkController,
  BenchmarkForm,
} from '@/features/benchmark/hooks/useBenchmark';

export const BENCHMARK_CONTROL_CLASS =
  'font-data mt-2 min-h-11 w-full border border-(--hairline) bg-(--surface) px-3 py-2 text-xs text-(--text) outline-none transition-colors hover:border-(--text-faint) focus-visible:border-(--gold) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--gold) disabled:cursor-not-allowed disabled:opacity-50';

export function benchmarkNumberValue(value: string, fallback: number): number {
  const parsed = Number(value);

  return Number.isFinite(parsed) ? parsed : fallback;
}

export function updateBenchmarkForm(
  controller: BenchmarkController,
  patch: Partial<BenchmarkForm>,
): void {
  controller.setForm((current) => ({
    ...current,
    ...patch,
  }));
}
