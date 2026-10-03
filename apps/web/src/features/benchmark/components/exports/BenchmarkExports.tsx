import type { BenchmarkRunResponse } from '@/features/benchmark/types';
import { downloadBenchmark } from '@/features/benchmark/lib/exportBuilders';
import { Button } from '@/shared/components/ui';

import type { JSX } from 'react';

const EXPORT_OPTIONS = [
  { format: 'json', label: 'Export JSON' },
  { format: 'csv', label: 'Export CSV' },
] as const;

interface BenchmarkExportsProps {
  result: BenchmarkRunResponse;
}

export function BenchmarkExports({
  result,
}: Readonly<BenchmarkExportsProps>): JSX.Element {
  return (
    <div className="flex flex-wrap gap-3">
      {EXPORT_OPTIONS.map((option) => (
        <Button
          className="border-(--hairline) text-(--text-soft) hover:border-(--teal) hover:text-(--teal) focus-visible:outline-(--teal)"
          key={option.format}
          variant="secondary"
          onClick={() => downloadBenchmark(result, option.format)}
        >
          {option.label}
        </Button>
      ))}
    </div>
  );
}
