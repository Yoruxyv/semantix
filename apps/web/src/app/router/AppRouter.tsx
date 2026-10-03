import { Suspense, type JSX } from 'react';
import { Route, Routes } from 'react-router';

import { AppLayout } from '../layouts/AppLayout';
import { RouteLoader } from './RouteLoader';
import routes from './routes';
import type { AppRouteDefinition } from './types';

function renderRoute(route: AppRouteDefinition): JSX.Element {
  const Component = route.component;
  const element = (
    <Suspense fallback={<RouteLoader />}>
      <Component />
    </Suspense>
  );

  if (route.index) {
    return <Route key={route.key} index element={element} />;
  }

  return (
    <Route key={route.key} path={route.path} element={element}>
      {route.children?.map(renderRoute)}
    </Route>
  );
}

export function AppRouter(): JSX.Element {
  return (
    <Routes>
      <Route element={<AppLayout />}>{routes.map(renderRoute)}</Route>
    </Routes>
  );
}
