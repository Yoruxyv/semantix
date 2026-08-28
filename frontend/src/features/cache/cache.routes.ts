import { defineLazyPathRoute } from '@/app/router/lazyPage';
import { APP_PATHS } from '@/app/navigation/navigationConfig';

const cacheRoutes = [
  defineLazyPathRoute(
    'cache-entry-detail',
    `${APP_PATHS.cache.slice(1)}/entries/:cacheKey`,
    () => import('./pages/CacheEntryDetailPage'),
    'CacheEntryDetailPage',
  ),
  defineLazyPathRoute(
    APP_PATHS.cache.slice(1),
    'cache',
    () => import('./pages/CachePage'),
    'CachePage',
  ),
];

export default cacheRoutes;
