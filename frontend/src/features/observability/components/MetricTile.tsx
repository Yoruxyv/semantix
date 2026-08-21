import type { JSX } from "react";
interface MetricTileProps {
  description: string;
  label: string;
  value: string;
}

export function MetricTile({
  description,
  label,
  value,
}: Readonly<MetricTileProps>): JSX.Element {
  return (
    <div className="min-w-0 basis-56 grow bg-(--surface) p-5">
      <dt className="ui-label text-(--text-muted)">{label}</dt>
      <dd>
        <span className="font-data mt-3 block text-2xl text-(--text)">
          {value}
        </span>
        <span className="mt-2 block text-xs/5 text-(--text-faint)">
          {description}
        </span>
      </dd>
    </div>
  );
}
