import { QueryClientProvider } from '@tanstack/react-query';
import { useMemo, type ReactNode, type JSX } from 'react';

import { AuthProvider } from '@/features/auth/context/AuthProvider';
import { CacheControlProvider } from '@/features/cache/context/CacheControlContext';
import { MonitorProvider } from '@/features/monitor/context/MonitorContext';
import { createAppQueryClient } from '@/shared/query/queryClient';

interface ProviderProps {
  children: ReactNode;
}

export function AppProviders({ children }: Readonly<ProviderProps>): JSX.Element {
  const queryClient = useMemo(() => createAppQueryClient(), []);

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

export function WorkspaceProviders({ children }: Readonly<ProviderProps>): JSX.Element {
  return (
    <CacheControlProvider>
      <MonitorProvider>{children}</MonitorProvider>
    </CacheControlProvider>
  );
}
