import type { ButtonHTMLAttributes, JSX } from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'link';

export type ButtonSize = 'compact' | 'default' | 'large' | 'wide' | 'none';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  size?: ButtonSize;
  variant?: ButtonVariant;
}

const BUTTON_VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    'ui-label border border-(--gold) bg-(--gold) text-(--ink) transition-colors hover:bg-transparent hover:text-(--gold) focus-visible:outline-2 focus-visible:outline-(--gold) active:translate-y-px disabled:cursor-not-allowed',
  secondary:
    'ui-label border transition-colors focus-visible:outline-2 active:translate-y-px disabled:cursor-not-allowed',
  danger:
    'ui-label bg-(--coral-text) text-(--ink) transition-opacity hover:opacity-85 focus-visible:outline-2 focus-visible:outline-(--coral) active:translate-y-px disabled:cursor-not-allowed',
  link: 'underline underline-offset-4 transition-colors focus-visible:outline-2 focus-visible:outline-current active:translate-y-px disabled:cursor-not-allowed',
};

const BUTTON_SIZE_CLASSES: Record<ButtonSize, string> = {
  compact: 'min-h-10 px-3 py-2 focus-visible:outline-offset-2',
  default: 'min-h-10 px-4 py-2 focus-visible:outline-offset-2',
  large: 'min-h-11 px-4 py-3 focus-visible:outline-offset-3',
  wide: 'min-h-11 px-5 py-3 focus-visible:outline-offset-3',
  none: 'focus-visible:outline-offset-2',
};

const DEFAULT_BUTTON_SIZE: Record<ButtonVariant, ButtonSize> = {
  primary: 'wide',
  secondary: 'default',
  danger: 'large',
  link: 'none',
};

export function Button({
  className,
  size,
  type = 'button',
  variant = 'secondary',
  ...props
}: Readonly<ButtonProps>): JSX.Element {
  const resolvedSize = size ?? DEFAULT_BUTTON_SIZE[variant];
  const classes = [
    BUTTON_VARIANT_CLASSES[variant],
    BUTTON_SIZE_CLASSES[resolvedSize],
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return <button className={classes} type={type} {...props} />;
}
