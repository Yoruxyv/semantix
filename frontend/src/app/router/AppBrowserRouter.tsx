import { BrowserRouter } from 'react-router';

import type { JSX, ReactNode } from 'react';

interface AppBrowserRouterProps {
  children: ReactNode;
}

export function AppBrowserRouter({
  children,
}: Readonly<AppBrowserRouterProps>): JSX.Element {
  return <BrowserRouter useTransitions={false}>{children}</BrowserRouter>;
}
