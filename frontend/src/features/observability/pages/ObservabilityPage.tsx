import { Link } from 'react-router';

import { APP_PATHS } from '@/app/navigation/navigationConfig';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { canAccessGlobalMetrics } from '@/features/auth/permissions';

import { ObservabilityDashboard } from '../components/ObservabilityDashboard';

import type { JSX } from 'react';

export function ObservabilityPage(): JSX.Element {
  const { session, status } = useAuth();

  if (!canAccessGlobalMetrics(status, session)) {
    return (
      <section aria-labelledby="metrics-access-heading" className="py-16">
        <p className="font-data text-sm text-(--coral-text)">403</p>
        <h1 className="font-display mt-2 text-4xl italic" id="metrics-access-heading">
          Global administrator access required
        </h1>
        <p className="mt-4 max-w-xl text-sm/6 text-(--text-muted)">
          Process-wide runtime metrics are restricted to global administrators.
          Namespace-scoped cache statistics remain available in the cache inspector.
        </p>
        <Link
          className="ui-label mt-8 inline-block border-b border-(--gold) pb-1 text-(--gold) focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-(--gold)"
          to={APP_PATHS.cache}
        >
          Open cache inspector
        </Link>
      </section>
    );
  }

  return <ObservabilityDashboard />;
}
