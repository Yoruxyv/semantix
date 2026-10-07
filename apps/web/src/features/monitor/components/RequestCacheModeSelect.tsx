import {
  useEffect,
  useId,
  useRef,
  useState,
  type JSX,
  type KeyboardEvent,
} from 'react';

import { QUERY_POLICY_LABELS, type QueryPolicyMode } from '../types';

const POLICY_OPTIONS: ReadonlyArray<{ description: string; mode: QueryPolicyMode }> = [
  {
    mode: 'normal',
    description: 'Read an eligible match or store a newly generated response.',
  },
  {
    mode: 'read-only',
    description: 'Read an eligible match but never store a generated response.',
  },
  {
    mode: 'refresh',
    description: 'Skip cache lookup, generate a response, and write it to cache.',
  },
  { mode: 'bypass', description: 'Skip cache reads and writes for this request.' },
  {
    mode: 'private',
    description:
      'Skip cache reads and writes. Prompt and response content are omitted from the recent query trace.',
  },
];

interface RequestCacheModeSelectProps {
  className: string;
  onChange: (mode: QueryPolicyMode) => void;
  value: QueryPolicyMode;
}

export function RequestCacheModeSelect({
  className,
  onChange,
  value,
}: Readonly<RequestCacheModeSelectProps>): JSX.Element {
  const id = useId();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const labelId = `${id}-label`;
  const valueId = `${id}-value`;
  const listId = `${id}-list`;
  const descriptionId = `${id}-description`;

  useEffect(() => {
    if (!isOpen) return undefined;
    listRef.current
      ?.querySelector<HTMLButtonElement>(`[role="option"][value="${value}"]`)
      ?.focus();
    function closeOnOutsidePointer(event: PointerEvent): void {
      if (
        event.target instanceof Node &&
        !containerRef.current?.contains(event.target)
      ) {
        setIsOpen(false);
      }
    }
    document.addEventListener('pointerdown', closeOnOutsidePointer);
    return () => document.removeEventListener('pointerdown', closeOnOutsidePointer);
  }, [isOpen, value]);

  function handleListKeyDown(event: KeyboardEvent<HTMLUListElement>): void {
    const options = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="option"]'),
    );
    const index = options.findIndex((option) => option === document.activeElement);
    let nextIndex: number;
    switch (event.key) {
      case 'ArrowDown':
        nextIndex = Math.min(options.length - 1, index + 1);
        break;
      case 'ArrowUp':
        nextIndex = Math.max(0, index - 1);
        break;
      case 'Home':
        nextIndex = 0;
        break;
      case 'End':
        nextIndex = options.length - 1;
        break;
      case 'Escape':
        event.preventDefault();
        event.stopPropagation();
        setIsOpen(false);
        triggerRef.current?.focus();
        return;
      case 'Tab':
        // Restore the trigger before native Tab navigation so unmounting the popup does not lose the focus order.
        setIsOpen(false);
        triggerRef.current?.focus();
        return;
      default:
        return;
    }
    event.preventDefault();
    options[nextIndex]?.focus();
  }

  return (
    <div
      ref={containerRef}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setIsOpen(false);
      }}
    >
      <label className="text-sm text-(--text-soft)" htmlFor={id} id={labelId}>
        Request cache mode
      </label>
      <div className="relative">
        <button
          ref={triggerRef}
          aria-controls={isOpen ? listId : undefined}
          aria-describedby={descriptionId}
          aria-expanded={isOpen}
          aria-haspopup="listbox"
          aria-labelledby={`${labelId} ${valueId}`}
          className={`${className} flex items-center justify-between gap-3 text-left`}
          id={id}
          type="button"
          onClick={() => setIsOpen((current) => !current)}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
              event.preventDefault();
              setIsOpen(true);
            }
          }}
        >
          <span id={valueId}>{QUERY_POLICY_LABELS[value]}</span>
          <span
            aria-hidden="true"
            className={`size-2 shrink-0 border-r border-b border-(--text-muted) ${isOpen ? 'rotate-225' : 'rotate-45'}`}
          />
        </button>
        {isOpen && (
          // eslint-disable-next-line jsx-a11y/prefer-tag-over-role -- The requested custom popup implements listbox keyboard and focus behavior; native select menus use OS styling.
          <ul
            ref={listRef}
            aria-labelledby={labelId}
            className="absolute inset-x-0 top-full z-20 mt-1 max-h-64 overflow-y-auto rounded-sm border border-(--hairline) bg-(--surface) p-1 shadow-lg"
            id={listId}
            role="listbox"
            onKeyDown={handleListKeyDown}
          >
            {POLICY_OPTIONS.map((option) => (
              <li key={option.mode} role="none">
                {/* eslint-disable-next-line jsx-a11y/prefer-tag-over-role -- Focusable buttons provide activation for custom listbox options, with no interactive children. */}
                <button
                  aria-selected={value === option.mode}
                  className={`flex min-h-11 w-full items-center gap-3 px-3 py-2 text-left text-sm outline-none hover:bg-[rgba(234,230,221,0.04)] focus:bg-[rgba(234,230,221,0.04)] focus-visible:outline-1 focus-visible:-outline-offset-1 focus-visible:outline-(--gold) ${value === option.mode ? 'text-(--gold)' : 'text-(--text)'}`}
                  role="option"
                  tabIndex={-1}
                  type="button"
                  value={option.mode}
                  onClick={() => {
                    onChange(option.mode);
                    setIsOpen(false);
                    triggerRef.current?.focus();
                  }}
                >
                  <span
                    aria-hidden="true"
                    className="font-data w-4 shrink-0 text-(--gold)"
                  >
                    {value === option.mode ? '✓' : ''}
                  </span>
                  <span>{QUERY_POLICY_LABELS[option.mode]}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <p
        className={
          value === 'private'
            ? 'font-data mt-2 text-[10px]/5 text-(--gold)'
            : 'font-data mt-2 text-[10px]/5 text-(--text-faint)'
        }
        id={descriptionId}
      >
        {POLICY_OPTIONS.find((option) => option.mode === value)?.description}
      </p>
    </div>
  );
}
