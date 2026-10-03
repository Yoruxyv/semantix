import type { JSX } from 'react';
import { useLocation } from 'react-router';

import { WorkspaceRouteSkeleton } from './WorkspaceRouteSkeleton';

export function RouteLoader(): JSX.Element {
  const { pathname } = useLocation();

  return (
    <output
      aria-label="Loading workspace"
      aria-live="polite"
      className="block min-h-64 animate-pulse border-y border-(--hairline) py-8"
    >
      <span className="ui-label block text-(--text-muted)">Loading workspace</span>
      <WorkspaceRouteSkeleton pathname={pathname} />
    </output>
  );
}
