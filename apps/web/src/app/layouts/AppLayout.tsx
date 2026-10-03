import { useRef, type RefObject, type JSX } from 'react';
import { Outlet } from 'react-router';

import { AuthPanel } from '@/features/auth/components/AuthPanel';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { useCacheControl } from '@/features/cache/hooks/useCacheControl';
import { Alert } from '@/shared/components/ui';
import { Navbar } from '../navigation/Navbar';
import { AppProviders, WorkspaceProviders } from '../providers/AppProviders';
import { RouteLoader } from '../router/RouteLoader';
import { useRouteAccessibility } from '../router/useRouteAccessibility';

interface WorkspaceProps {
  readonly mainRef: RefObject<HTMLElement | null>;
}

function Workspace({ mainRef }: WorkspaceProps): JSX.Element {
  const { clearControlError, controlError } = useCacheControl();

  return (
    <>
      {controlError !== null && (
        <Alert
          action={
            <button
              className="ui-label text-(--text-muted) focus-visible:outline-1 focus-visible:outline-offset-3 focus-visible:outline-(--gold)"
              type="button"
              onClick={clearControlError}
            >
              Dismiss
            </button>
          }
          className="font-data mt-5 border-l border-(--coral) pl-4 text-[11px] text-(--coral-text)"
          role="alert"
          tone="error"
        >
          <span>{controlError}</span>
        </Alert>
      )}

      <main className="py-10 sm:py-12" id="main-content" ref={mainRef} tabIndex={-1}>
        <Outlet />
      </main>
    </>
  );
}

function AppShell(): JSX.Element {
  const { session, status } = useAuth();
  const mainRef = useRef<HTMLElement>(null);
  const canAccessWorkspace = status === 'disabled' || status === 'authenticated';
  const workspaceKey = JSON.stringify([
    status,
    session?.name ?? null,
    session?.role ?? null,
    session?.namespaces ?? [],
  ]);

  useRouteAccessibility(mainRef);

  let content: JSX.Element;
  if (status === 'loading') {
    content = (
      <main className="py-8 sm:py-10" id="main-content" ref={mainRef} tabIndex={-1}>
        <RouteLoader />
      </main>
    );
  } else if (canAccessWorkspace) {
    content = (
      <>
        <AuthPanel />
        <WorkspaceProviders key={workspaceKey}>
          <Workspace mainRef={mainRef} />
        </WorkspaceProviders>
      </>
    );
  } else {
    content = (
      <main className="py-8 sm:py-10" id="main-content" ref={mainRef} tabIndex={-1}>
        <AuthPanel />
      </main>
    );
  }

  return (
    <div className="min-h-screen bg-(--ink) px-4 text-(--text) sm:px-8">
      <a
        className="ui-label fixed left-4 top-3 z-50 -translate-y-20 bg-(--gold) px-3 py-2 text-(--ink) focus:translate-y-0"
        href="#main-content"
      >
        Skip to content
      </a>
      <div className="mx-auto max-w-6xl">
        <Navbar />
        {content}
      </div>
    </div>
  );
}

export function AppLayout(): JSX.Element {
  return (
    <AppProviders>
      <AppShell />
    </AppProviders>
  );
}
