import { APP_PATHS } from '@/app/navigation/navigationConfig';
import { defineLazyPathRoute } from '@/app/router/lazyPage';
import type { AppRouteDefinition } from '@/app/router/types';
import { LegacyBenchmarksRedirect } from './pages/LegacyBenchmarksRedirect';

const benchmarkRoutes: AppRouteDefinition[] = [
  defineLazyPathRoute(
    'evaluations',
    APP_PATHS.evaluations.slice(1),
    () => import('./pages/BenchmarksPage'),
    'BenchmarksPage',
  ),
  {
    key: 'legacy-benchmarks-redirect',
    path: APP_PATHS.benchmarks.slice(1),
    component: LegacyBenchmarksRedirect,
  },
];

export default benchmarkRoutes;
