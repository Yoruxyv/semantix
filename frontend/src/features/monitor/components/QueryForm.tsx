import { useState, type JSX, type SubmitEvent } from 'react';

import { useAuth } from '@/features/auth/hooks/useAuth';
import { canSubmitQueries } from '@/features/auth/permissions';
import {
  CACHE_NAMESPACE_PATTERN_SOURCE,
  isCacheNamespace,
  MAX_CACHE_NAMESPACE_LENGTH,
} from '@/features/cache/namespace';
import { Button } from '@/shared/components/ui';
import { formatCount } from '@/shared/lib/formatters';

import {
  QUERY_POLICY_LABELS,
  type QueryPolicyMode,
  type QueryRequest,
  type QuerySubmission,
} from '../types';

interface QueryFormProps {
  isLoading: boolean;
  onSubmit: (submission: QuerySubmission) => Promise<void>;
}

const EXAMPLE_PROMPTS = [
  'Explain semantic caching in simple terms',
  'How does cosine similarity work?',
];

const MAX_PROMPT_LENGTH = 2_000;
const MAX_PROMPT_LENGTH_LABEL = formatCount(MAX_PROMPT_LENGTH);

const POLICY_OPTIONS: ReadonlyArray<{
  description: string;
  mode: QueryPolicyMode;
}> = [
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
  {
    mode: 'bypass',
    description: 'Skip cache reads and writes for this request.',
  },
  {
    mode: 'private',
    description:
      'Skip cache reads and writes. Prompt and response content are omitted from the recent query trace.',
  },
];

const POLICY_FIELDS: Record<
  QueryPolicyMode,
  Omit<QueryRequest, 'namespace' | 'prompt'>
> = {
  normal: {
    cache_enabled: true,
    cache_read_enabled: true,
    cache_write_enabled: true,
    private: false,
  },
  'read-only': {
    cache_enabled: true,
    cache_read_enabled: true,
    cache_write_enabled: false,
    private: false,
  },
  refresh: {
    cache_enabled: true,
    cache_read_enabled: false,
    cache_write_enabled: true,
    private: false,
  },
  bypass: {
    cache_enabled: false,
    cache_read_enabled: false,
    cache_write_enabled: false,
    private: false,
  },
  private: {
    cache_enabled: false,
    cache_read_enabled: false,
    cache_write_enabled: false,
    private: true,
  },
};

const CONTROL_CLASS =
  'mt-2 min-h-11 w-full min-w-0 border border-(--hairline) bg-(--surface) px-3 py-2 text-sm text-(--text) outline-none focus-visible:border-(--gold) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--gold)';

export function QueryForm({
  isLoading,
  onSubmit,
}: Readonly<QueryFormProps>): JSX.Element {
  const { session, status } = useAuth();
  const canSubmit = canSubmitQueries(status, session);
  const explicitNamespaces =
    session?.namespaces.filter((namespace) => namespace !== '*') ?? [];
  const hasWildcardNamespace =
    status === 'disabled' || (session?.namespaces.includes('*') ?? false);
  let defaultNamespace = '';
  if (hasWildcardNamespace) {
    defaultNamespace = 'default';
  } else if (explicitNamespaces.length === 1) {
    defaultNamespace = explicitNamespaces[0] ?? '';
  }
  const [prompt, setPrompt] = useState('');
  const [namespace, setNamespace] = useState(defaultNamespace);
  const [policyMode, setPolicyMode] = useState<QueryPolicyMode>('normal');
  const [promptError, setPromptError] = useState<string | null>(null);
  const [namespaceError, setNamespaceError] = useState<string | null>(null);
  const normalizedNamespace = namespace.trim();
  const namespaceValid =
    isCacheNamespace(normalizedNamespace) &&
    (hasWildcardNamespace || explicitNamespaces.includes(normalizedNamespace));

  async function handleSubmit(event: SubmitEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();

    const normalizedPrompt = prompt.trim();

    if (!canSubmit) {
      return;
    }

    if (normalizedPrompt.length === 0) {
      setPromptError('A blank prompt has no semantic neighborhood.');
      return;
    }

    if (normalizedPrompt.length > MAX_PROMPT_LENGTH) {
      setPromptError(
        `Keep the prompt at or below ${MAX_PROMPT_LENGTH_LABEL} characters.`,
      );
      return;
    }

    if (!namespaceValid) {
      setNamespaceError('Choose one authorized cache namespace.');
      return;
    }

    setPromptError(null);
    setNamespaceError(null);
    await onSubmit({
      policyMode,
      request: {
        prompt: normalizedPrompt,
        namespace: normalizedNamespace,
        ...POLICY_FIELDS[policyMode],
      },
    });
  }

  let submitLabel = 'Run query';
  if (isLoading) {
    submitLabel = 'Embedding + lookup…';
  } else if (!canSubmit) {
    submitLabel = 'Operator access required';
  }

  return (
    <section aria-labelledby="query-heading">
      <div className="mb-5 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <h1 className="font-display text-3xl italic" id="query-heading">
            Probe the cache
          </h1>

          <p className="mt-2 max-w-2xl text-sm/6 text-(--text-muted)">
            Each prompt is embedded, compared with the nearest stored vector, then
            either reused or sent upstream.
          </p>
        </div>

        <p className="ui-label text-(--text-faint)">
          Max {MAX_PROMPT_LENGTH_LABEL} chars
        </p>
      </div>

      <form aria-busy={isLoading} onSubmit={(event) => void handleSubmit(event)}>
        <label className="ui-label mb-2 block text-(--text-muted)" htmlFor="prompt">
          Query text
        </label>

        <textarea
          id="prompt"
          aria-describedby={
            promptError === null ? 'prompt-note' : 'prompt-note prompt-error'
          }
          aria-invalid={promptError !== null}
          className="scrollbar-thin block min-h-36 w-full resize-y border border-(--hairline) bg-(--surface) p-4 text-sm/6 text-(--text) outline-none transition-colors placeholder:text-(--text-faint) hover:border-(--text-faint) focus-visible:border-(--gold) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--gold) disabled:cursor-not-allowed disabled:opacity-55"
          disabled={isLoading}
          maxLength={MAX_PROMPT_LENGTH}
          name="prompt"
          placeholder="Describe the thing you want the cache to recognize."
          rows={6}
          value={prompt}
          onChange={(event) => {
            setPrompt(event.target.value);
            setPromptError(null);
          }}
        />

        <div className="font-data mt-2 flex items-start justify-between gap-4 text-[10px] text-(--text-faint)">
          <p id="prompt-note">
            Focused wording makes the neighborhood easier to inspect.
          </p>

          <span className="shrink-0 tabular-nums">
            {prompt.length} / {MAX_PROMPT_LENGTH_LABEL}
          </span>
        </div>

        {promptError !== null && (
          <p
            className="font-data mt-3 border-l-2 border-(--coral) pl-3 text-[11px]/5 text-(--coral-text)"
            id="prompt-error"
            role="alert"
          >
            {promptError}
          </p>
        )}

        <details className="mt-5 border-y border-(--hairline) py-4">
          <summary className="ui-label min-h-11 cursor-pointer py-3 text-(--teal) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--teal)">
            Advanced cache policy
          </summary>

          <div className="mt-4 grid gap-6 lg:grid-cols-2">
            <div>
              <p className="ui-label text-(--text-muted)">Cache namespace</p>

              {hasWildcardNamespace && (
                <label className="mt-3 block">
                  <span className="text-sm text-(--text-soft)">Explicit namespace</span>
                  <input
                    aria-describedby="query-namespace-note"
                    aria-invalid={namespaceError !== null}
                    className={CONTROL_CLASS}
                    maxLength={MAX_CACHE_NAMESPACE_LENGTH}
                    pattern={CACHE_NAMESPACE_PATTERN_SOURCE}
                    spellCheck={false}
                    value={namespace}
                    onChange={(event) => {
                      setNamespace(event.target.value);
                      setNamespaceError(null);
                    }}
                  />
                </label>
              )}

              {!hasWildcardNamespace && explicitNamespaces.length > 1 && (
                <label className="mt-3 block">
                  <span className="text-sm text-(--text-soft)">
                    Authorized namespace
                  </span>
                  <select
                    aria-describedby="query-namespace-note"
                    aria-invalid={namespaceError !== null}
                    className={CONTROL_CLASS}
                    value={namespace}
                    onChange={(event) => {
                      setNamespace(event.target.value);
                      setNamespaceError(null);
                    }}
                  >
                    <option value="">Choose a namespace</option>
                    {explicitNamespaces.map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </label>
              )}

              {!hasWildcardNamespace && explicitNamespaces.length <= 1 && (
                <p className="font-data mt-3 wrap-break-word text-xs text-(--text-soft)">
                  {normalizedNamespace || 'No authorized namespace'}
                </p>
              )}

              <p
                className="font-data mt-2 text-[10px]/5 text-(--text-faint)"
                id="query-namespace-note"
              >
                Requests use one authorized namespace. Wildcard access never sends the
                global marker.
              </p>

              {namespaceError !== null && (
                <p
                  className="font-data mt-2 text-[10px]/5 text-(--coral-text)"
                  role="alert"
                >
                  {namespaceError}
                </p>
              )}
            </div>

            <fieldset>
              <legend className="ui-label text-(--text-muted)">
                Request cache mode
              </legend>

              <div className="mt-3 space-y-3">
                {POLICY_OPTIONS.map((option) => {
                  const controlId = `query-policy-${option.mode}`;
                  const descriptionId = `query-policy-${option.mode}-description`;
                  return (
                    <div
                      className="flex min-h-11 items-start gap-3 border-l border-(--hairline) py-2 pl-3"
                      key={option.mode}
                    >
                      <input
                        aria-describedby={descriptionId}
                        checked={policyMode === option.mode}
                        className="mt-1 size-4 accent-(--gold)"
                        id={controlId}
                        name="query-policy"
                        type="radio"
                        value={option.mode}
                        onChange={() => setPolicyMode(option.mode)}
                      />
                      <span className="min-w-0">
                        <label
                          className="block cursor-pointer text-sm text-(--text-soft)"
                          htmlFor={controlId}
                        >
                          {QUERY_POLICY_LABELS[option.mode]}
                        </label>
                        <span
                          className={
                            option.mode === 'private'
                              ? 'font-data mt-1 block text-[10px]/5 text-(--gold)'
                              : 'font-data mt-1 block text-[10px]/5 text-(--text-faint)'
                          }
                          id={descriptionId}
                        >
                          {option.description}
                        </span>
                      </span>
                    </div>
                  );
                })}
              </div>
            </fieldset>
          </div>
        </details>

        <output
          aria-live="polite"
          className="font-data mt-4 block wrap-break-word border-l border-(--gold) pl-3 text-[11px]/5 text-(--text-muted)"
        >
          Effective request: namespace{' '}
          {namespaceValid ? normalizedNamespace : 'not selected'} ·{' '}
          {QUERY_POLICY_LABELS[policyMode]}.
        </output>

        {!canSubmit && (
          <p className="mt-4 text-xs/5 text-(--coral-text)" id="query-access-note">
            Operator or administrator access is required to run live queries.
          </p>
        )}

        <div className="mt-6 flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="ui-label mb-2 text-(--text-faint)">Sample probes</p>

            <div className="flex flex-col items-start gap-1.5">
              {EXAMPLE_PROMPTS.map((example) => (
                <button
                  key={example}
                  className="min-h-8 text-left text-xs text-(--teal) underline decoration-[rgba(91,156,148,0.35)] underline-offset-4 transition-colors hover:text-(--text) focus-visible:outline-1 focus-visible:outline-offset-3 focus-visible:outline-(--teal) active:translate-y-px disabled:opacity-50"
                  disabled={isLoading}
                  type="button"
                  onClick={() => setPrompt(example)}
                >
                  {example}
                </button>
              ))}
            </div>
          </div>

          <Button
            aria-describedby={canSubmit ? undefined : 'query-access-note'}
            className="w-full disabled:opacity-55 lg:w-auto"
            disabled={isLoading || !canSubmit || !namespaceValid}
            type="submit"
            variant="primary"
          >
            {submitLabel}
          </Button>
        </div>
      </form>
    </section>
  );
}
