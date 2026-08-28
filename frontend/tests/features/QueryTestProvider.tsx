import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import type { JSX, ReactNode } from 'react';

interface QueryTestProviderProps {
  children: ReactNode;
  client: QueryClient;
}

export function QueryTestProvider({
  children,
  client,
}: Readonly<QueryTestProviderProps>): JSX.Element {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
