import type { HTMLAttributes, ReactNode, JSX } from 'react';

type AlertTone = 'error' | 'warning' | 'info';

interface AlertProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  action?: ReactNode;
  children: ReactNode;
  title?: string;
  tone?: AlertTone;
}

const ALERT_TONE_CLASSES: Record<AlertTone, string> = {
  error: 'text-(--coral-text)',
  warning: 'text-(--gold)',
  info: 'text-(--teal)',
};

export function Alert({
  action,
  children,
  className,
  title,
  tone = 'info',
  ...props
}: Readonly<AlertProps>): JSX.Element {
  const classes = [ALERT_TONE_CLASSES[tone], className].filter(Boolean).join(' ');

  return (
    <div className={classes} {...props}>
      <div
        className={
          action === undefined
            ? undefined
            : 'flex flex-wrap items-center justify-between gap-4'
        }
      >
        <div>
          {title !== undefined && <p className="ui-label">{title}</p>}
          <div>{children}</div>
        </div>
        {action}
      </div>
    </div>
  );
}
