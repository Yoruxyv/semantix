import type { JSX } from 'react';

import type { BenchmarkController } from '@/features/benchmark/hooks/useBenchmark';
import { BenchmarkDatasetControls } from './BenchmarkDatasetControls';
import { BenchmarkRunOptions } from './BenchmarkRunOptions';
import { BenchmarkSweepControls } from './BenchmarkSweepControls';

interface BenchmarkControlsProps {
  controller: BenchmarkController;
}

export function BenchmarkControls({
  controller,
}: Readonly<BenchmarkControlsProps>): JSX.Element {
  return (
    <div
      className="grid gap-5 border-y border-(--hairline) py-6 sm:grid-cols-2 lg:grid-cols-3"
      data-benchmark-controls
    >
      <BenchmarkDatasetControls controller={controller} />
      <BenchmarkRunOptions controller={controller} />
      <BenchmarkSweepControls controller={controller} />
    </div>
  );
}
