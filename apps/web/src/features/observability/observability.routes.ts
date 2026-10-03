import { defineLazyPathRoute } from '@/app/router/lazyPage';
import { APP_PATHS } from '@/app/navigation/navigationConfig';

const observabilityRoutes = [
  defineLazyPathRoute(
    APP_PATHS.observability.slice(1),
    'observability',
    () => import('./pages/ObservabilityPage'),
    'ObservabilityPage',
  ),
];

export default observabilityRoutes;
