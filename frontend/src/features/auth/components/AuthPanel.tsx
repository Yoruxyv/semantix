import { useEffect, useState, type JSX, type SubmitEvent } from 'react';

import { useAuth } from '../hooks/useAuth';

const ACCESS_POLICY_ERROR =
  'Access policy unavailable. Semantix could not determine the current ' +
  'authentication policy. Please wait a moment and try again.';
const SESSION_VERIFICATION_ERROR =
  'Session verification unavailable. Semantix could not verify the current ' +
  'authentication session. Please wait a moment and try again.';

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes.toString().padStart(2, '0')}:${remainingSeconds
    .toString()
    .padStart(2, '0')}`;
}

interface BootstrapErrorPanelProps {
  error: string | null;
  isSessionError: boolean;
  retry: () => void;
}

function BootstrapErrorPanel({
  error,
  isSessionError,
  retry,
}: Readonly<BootstrapErrorPanelProps>): JSX.Element {
  return (
    <section
      aria-labelledby="access-policy-heading"
      className="mx-auto flex min-h-96 max-w-xl items-center py-2"
    >
      <div className="relative w-full overflow-hidden border border-(--hairline) border-l-2 border-l-(--gold) bg-(--surface) px-5 py-7 sm:px-8 sm:py-9">
        <div
          aria-hidden="true"
          className="absolute right-0 top-0 h-px w-24 bg-(--gold)"
        />
        <p className="ui-label text-(--gold)">
          {isSessionError ? 'Session verification' : 'Access policy'}
        </p>
        <h1
          className="font-display mt-3 text-3xl italic text-(--text)"
          id="access-policy-heading"
        >
          {isSessionError ? 'Session verification paused' : 'Workspace access paused'}
        </h1>
        <div className="min-h-24 pt-4">
          <p className="max-w-md text-sm/6 text-(--text-muted)" role="alert">
            {error ??
              (isSessionError ? SESSION_VERIFICATION_ERROR : ACCESS_POLICY_ERROR)}
          </p>
          <button
            className="ui-label mt-5 min-h-11 border border-(--gold) bg-(--gold) px-5 py-2.5 text-(--ink) transition-colors hover:bg-transparent hover:text-(--gold) focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-(--gold)"
            type="button"
            onClick={retry}
          >
            Retry
          </button>
        </div>
      </div>
    </section>
  );
}

export function AuthPanel(): JSX.Element | null {
  const {
    authenticate,
    error,
    lockedUntil,
    logout,
    retryAccessPolicy,
    session,
    status,
  } = useAuth();
  const [token, setToken] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [currentTime, setCurrentTime] = useState(Date.now);

  useEffect(() => {
    if (lockedUntil === null) {
      return undefined;
    }

    setCurrentTime(Date.now());
    const timer = window.setInterval(() => {
      const now = Date.now();
      setCurrentTime(now);
      if (now >= lockedUntil) {
        window.clearInterval(timer);
      }
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [lockedUntil]);

  if (status === 'disabled' || status === 'loading') {
    return null;
  }

  if (status === 'error' || status === 'session-error') {
    return (
      <BootstrapErrorPanel
        error={error}
        isSessionError={status === 'session-error'}
        retry={retryAccessPolicy}
      />
    );
  }

  if (status === 'authenticated' && session !== null) {
    const namespaces =
      session.namespaces.length === 1 && session.namespaces[0] === '*'
        ? 'All'
        : session.namespaces.join(', ');
    return (
      <section
        aria-labelledby="authenticated-access-heading"
        className="relative mt-4 overflow-hidden border border-(--hairline) border-l-2 border-l-(--teal) bg-(--surface)"
      >
        <div className="flex flex-wrap items-center justify-between gap-4 px-4 py-3 sm:px-5">
          <div className="flex min-w-0 items-center gap-3">
            <span
              aria-hidden="true"
              className="size-2 shrink-0 rounded-full bg-(--teal) shadow-[0_0_0_4px_rgba(91,156,148,0.12)]"
            />
            <div className="min-w-0">
              <p className="ui-label text-(--teal)" id="authenticated-access-heading">
                Authenticated access
              </p>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1">
                <strong className="font-data text-[11px] font-medium text-(--text)">
                  {session.name}
                </strong>
                <span aria-hidden="true" className="text-[9px] text-(--text-faint)">
                  /
                </span>
                <span className="ui-label border border-(--hairline) px-1.5 py-0.5 text-[9px] text-(--text-muted)">
                  {session.role}
                </span>
                <span className="font-data min-w-0 text-[10px] text-(--text-muted)">
                  Namespaces: {namespaces}
                </span>
              </div>
            </div>
          </div>
          <button
            className="ui-label min-h-10 border border-(--hairline) bg-(--ink) px-4 py-2 text-(--text-muted) transition-colors hover:border-(--gold) hover:text-(--gold) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--gold)"
            type="button"
            onClick={logout}
          >
            Sign out
          </button>
        </div>
      </section>
    );
  }

  const remainingSeconds =
    lockedUntil === null
      ? 0
      : Math.max(0, Math.ceil((lockedUntil - currentTime) / 1_000));
  const isLocked = remainingSeconds > 0;
  const controlsDisabled = isLocked || isSubmitting;

  async function submit(event: SubmitEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (controlsDisabled) {
      return;
    }

    setIsSubmitting(true);
    const accepted = await authenticate(token);
    setIsSubmitting(false);
    if (accepted) {
      setToken('');
    }
  }

  return (
    <section
      aria-labelledby="authentication-gate-heading"
      className="mx-auto flex min-h-96 max-w-xl items-center py-2"
    >
      <div className="relative w-full overflow-hidden border border-(--hairline) border-l-2 border-l-(--gold) bg-(--surface) px-5 py-7 sm:px-8 sm:py-9">
        <div
          aria-hidden="true"
          className="absolute right-0 top-0 h-px w-24 bg-(--gold)"
        />
        <p className="ui-label text-(--gold)">Restricted workspace</p>
        <h1
          className="font-display mt-3 text-3xl italic text-(--text)"
          id="authentication-gate-heading"
        >
          Authentication required
        </h1>
        <p className="mt-2 text-sm/6 text-(--text-muted)">
          Enter your Semantix access token to continue.
        </p>

        <form className="mt-7" onSubmit={submit}>
          <label className="block" htmlFor="access-token">
            <span className="ui-label text-(--text-faint)">Access token</span>
          </label>
          <input
            autoComplete="off"
            className="font-data mt-2 min-h-11 w-full border border-(--hairline) bg-(--ink) px-3 py-2.5 text-[11px] text-(--text) outline-none transition-colors hover:border-(--text-faint) focus-visible:border-(--gold) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--gold) disabled:cursor-not-allowed disabled:opacity-55"
            disabled={controlsDisabled}
            id="access-token"
            name="access-token"
            type="password"
            value={token}
            onChange={(event) => setToken(event.target.value)}
          />
          <button
            className="ui-label mt-4 min-h-11 border border-(--gold) bg-(--gold) px-5 py-2.5 text-(--ink) transition-colors hover:bg-transparent hover:text-(--gold) focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-(--gold) disabled:cursor-not-allowed disabled:opacity-50"
            disabled={controlsDisabled}
            type="submit"
          >
            {isSubmitting ? 'Verifying…' : 'Authenticate'}
          </button>
        </form>

        <div className="min-h-16 pt-4">
          {error !== null && (lockedUntil === null || isLocked) && (
            <div className="font-data text-[10px]/5 text-(--coral-text)">
              <p role="alert">{error}</p>
              {isLocked && (
                <p aria-live="polite" className="mt-1 text-(--text-muted)">
                  Try again in {formatDuration(remainingSeconds)}.
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
