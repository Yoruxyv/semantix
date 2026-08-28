import type { JSX } from 'react';
import { Navigate, useLocation } from 'react-router';

import { APP_PATHS } from '@/app/navigation/navigationConfig';

export function LegacyBenchmarksRedirect(): JSX.Element {
  const { hash, search } = useLocation();

  return (
    <Navigate
      replace
      to={{
        pathname: APP_PATHS.evaluations,
        search,
        hash,
      }}
    />
  );
}
