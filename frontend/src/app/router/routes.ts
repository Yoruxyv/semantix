import { NotFoundPage } from '../pages/NotFoundPage';
import benchmarkRoutes from '@/features/benchmark/benchmark.routes';
import cacheRoutes from '@/features/cache/cache.routes';
import monitorRoutes from '@/features/monitor/monitor.routes';
import observabilityRoutes from '@/features/observability/observability.routes';
import type { AppRouteDefinition } from './types';

const routes: AppRouteDefinition[] = [
  ...monitorRoutes,
  ...cacheRoutes,
  ...benchmarkRoutes,
  ...observabilityRoutes,
  {
    key: 'not-found',
    path: '*',
    component: NotFoundPage,
  },
];

function matchesPath(route: AppRouteDefinition, pathname: string): boolean {
  if (route.index) {
    return pathname === '/';
  }

  if (route.path === '*') {
    return false;
  }

  const routePath = `/${route.path}`;
  return pathname === routePath || pathname.startsWith(`${routePath}/`);
}

export async function preloadRouteModule(pathname: string): Promise<void> {
  const route = routes.find((candidate) => matchesPath(candidate, pathname));
  await route?.preload?.();
}

export default routes;
