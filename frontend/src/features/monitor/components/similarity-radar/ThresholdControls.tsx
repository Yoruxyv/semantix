import { Button } from '@/shared/components/ui';
import { formatDecimal } from '@/shared/lib/formatters';

import type { JSX } from "react";

interface ThresholdControlsProps {
  appliedThreshold: number;
  canApplyThreshold: boolean;
  isApplyingThreshold: boolean;
  onThresholdApply: (threshold: number) => void;
  onThresholdChange: (threshold: number) => void;
  threshold: number;
}

export function ThresholdControls({
  appliedThreshold,
  canApplyThreshold,
  isApplyingThreshold,
  onThresholdApply,
  onThresholdChange,
  threshold,
}: Readonly<ThresholdControlsProps>): JSX.Element {
  const hasPendingThreshold = Math.abs(threshold - appliedThreshold) >= 0.001;

  return (
    <div className="mt-7">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <label
          className="ui-label text-(--text-muted)"
          htmlFor="projection-threshold"
        >
          Projection threshold
        </label>

        <div className="font-data flex gap-4 text-[10px]">
          <span className="text-(--teal)">
            Preview {formatDecimal(threshold, 2)}
          </span>

          <span className="text-(--gold)">
            Backend applied {formatDecimal(appliedThreshold, 2)}
          </span>
        </div>
      </div>

      <input
        aria-describedby="threshold-note"
        className="threshold-range"
        id="projection-threshold"
        max="1"
        min="0"
        step="0.01"
        type="range"
        value={threshold}
        onChange={(event) => onThresholdChange(Number(event.target.value))}
      />

      <div className="font-data mt-3 flex justify-between text-[10px] text-(--text-faint)">
        <span>0.00 / permissive</span>
        <span>1.00 / exact</span>
      </div>

      <div className="mt-5 flex flex-wrap gap-3">
        {canApplyThreshold ? (
          <Button
            className="border-(--gold) text-(--gold) hover:bg-(--gold) hover:text-(--ink) focus-visible:outline-(--gold) disabled:opacity-40"
            disabled={!hasPendingThreshold || isApplyingThreshold}
            size="compact"
            variant="secondary"
            onClick={() => onThresholdApply(threshold)}
          >
            {isApplyingThreshold ? 'Applying' : 'Apply to cache'}
          </Button>
        ) : (
          <p className="font-data max-w-sm text-[10px]/5 text-(--text-faint)">
            Preview only. Applying the global threshold requires an
            administrator with wildcard namespace access.
          </p>
        )}

        <button
          className="ui-label min-h-10 border-b border-(--teal) px-1 py-2 text-(--teal) transition-colors hover:text-(--text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--teal) active:translate-y-px disabled:cursor-not-allowed disabled:opacity-40"
          disabled={!hasPendingThreshold || isApplyingThreshold}
          type="button"
          onClick={() => onThresholdChange(appliedThreshold)}
        >
          Reset preview
        </button>
      </div>

      <p
        className="mt-5 max-w-xl text-xs/5 text-(--text-muted)"
        id="threshold-note"
      >
        Every dot sits at its real similarity score. Vertical position only
        prevents overlap. Hover, focus, or select a trace to inspect its prompt
        and cache decision. Moving the slider previews which scored traces would
        qualify; it does not change backend behavior until you select Apply to
        cache.
      </p>
    </div>
  );
}
