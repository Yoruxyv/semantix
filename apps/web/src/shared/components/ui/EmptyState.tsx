import type { ReactNode, JSX } from 'react';

interface EmptyStateProps {
  className?: string;
  description: ReactNode;
  title: string;
}

export function EmptyState({
  className,
  description,
  title,
}: Readonly<EmptyStateProps>): JSX.Element {
  const classes = ['border-y border-(--hairline)', className].filter(Boolean).join(' ');

  return (
    <section className={classes}>
      <p className="font-display text-xl italic text-(--text-soft)">{title}</p>
      <div className="mt-2 max-w-2xl text-sm/6 text-(--text-muted)">{description}</div>
    </section>
  );
}
