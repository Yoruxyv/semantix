import { defineLazyIndexRoute } from '@/app/router/lazyPage';

const monitorRoutes = [
  defineLazyIndexRoute('monitor', () => import('./pages/MonitorPage'), 'MonitorPage'),
];

export default monitorRoutes;
