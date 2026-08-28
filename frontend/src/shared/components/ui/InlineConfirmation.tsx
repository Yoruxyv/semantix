import type { ReactNode, JSX } from 'react';

import { Button } from './Button';

interface InlineConfirmationProps {
  actionsClassName?: string;
  ariaLabel: string;
  className?: string;
  confirmAriaLabel?: string;
  confirmLabel: string;
  isPending: boolean;
  message: ReactNode;
  messageClassName?: string;
  onCancel: () => void;
  onConfirm: () => void;
  pendingLabel: string;
}

export function InlineConfirmation({
  actionsClassName,
  ariaLabel,
  className,
  confirmAriaLabel,
  confirmLabel,
  isPending,
  message,
  messageClassName,
  onCancel,
  onConfirm,
  pendingLabel,
}: Readonly<InlineConfirmationProps>): JSX.Element {
  const classes = ['min-w-0 border-0 border-l border-(--coral) p-0 pl-4', className]
    .filter(Boolean)
    .join(' ');

  return (
    <fieldset aria-label={ariaLabel} className={classes}>
      <div className={`text-(--text-soft) ${messageClassName ?? 'text-sm'}`}>
        {message}
      </div>
      <div className={`mt-3 flex flex-wrap ${actionsClassName ?? 'gap-4'}`}>
        <Button
          aria-label={confirmAriaLabel}
          className="ui-label min-h-9 text-(--coral-text) focus-visible:outline-(--coral) disabled:opacity-50"
          disabled={isPending}
          variant="link"
          onClick={onConfirm}
        >
          {isPending ? pendingLabel : confirmLabel}
        </Button>
        <Button
          className="ui-label min-h-9 text-(--teal) focus-visible:outline-(--teal) disabled:opacity-50"
          disabled={isPending}
          variant="link"
          onClick={onCancel}
        >
          Cancel
        </Button>
      </div>
    </fieldset>
  );
}
