export const APP_PATHS = {
  monitor: '/',
  cache: '/cache',
  evaluations: '/evaluations',
  benchmarks: '/benchmarks',
  observability: '/observability',
} as const;

export const NAV_ITEMS = [
  { label: 'Monitor', to: APP_PATHS.monitor },
  { label: 'Cache', to: APP_PATHS.cache },
  { label: 'Evaluations', to: APP_PATHS.evaluations },
  { label: 'Observability', to: APP_PATHS.observability },
] as const;
