import type { ReactNode, JSX } from 'react';

type PageHeaderSize = 'default' | 'large';
type PageHeaderTone = 'gold' | 'teal';

interface PageHeaderProps {
  actions?: ReactNode;
  className?: string;
  description: ReactNode;
  eyebrow: string;
  headingId?: string;
  size?: PageHeaderSize;
  title: string;
  tone?: PageHeaderTone;
}

const EYEBROW_TONE_CLASSES: Record<PageHeaderTone, string> = {
  gold: 'text-(--gold)',
  teal: 'text-(--teal)',
};

const TITLE_SIZE_CLASSES: Record<PageHeaderSize, string> = {
  default: 'mt-1 text-3xl',
  large: 'mt-2 text-4xl sm:text-5xl',
};

const DESCRIPTION_SIZE_CLASSES: Record<PageHeaderSize, string> = {
  default: 'max-w-3xl',
  large: 'max-w-2xl',
};

const ACTION_LAYOUT_CLASSES: Record<PageHeaderSize, string> = {
  default: 'flex flex-wrap items-end justify-between gap-4',
  large: 'flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between',
};

export function PageHeader({
  actions,
  className,
  description,
  eyebrow,
  headingId,
  size = 'default',
  title,
  tone = 'gold',
}: Readonly<PageHeaderProps>): JSX.Element {
  const hasActions = actions !== undefined && actions !== null && actions !== false;

  const classes = [hasActions ? ACTION_LAYOUT_CLASSES[size] : undefined, className]
    .filter(Boolean)
    .join(' ');

  return (
    <header className={classes}>
      <div>
        <p className={`ui-label ${EYEBROW_TONE_CLASSES[tone]}`}>{eyebrow}</p>

        <h1
          className={`font-display italic text-(--text) ${TITLE_SIZE_CLASSES[size]}`}
          id={headingId}
        >
          {title}
        </h1>

        <div
          className={`mt-3 text-sm/6 text-(--text-muted) ${DESCRIPTION_SIZE_CLASSES[size]}`}
        >
          {description}
        </div>
      </div>

      {hasActions ? actions : null}
    </header>
  );
}
