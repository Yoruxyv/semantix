import { useEffect, useRef, type RefObject } from 'react';
import { useLocation, useNavigationType } from 'react-router';

import { APP_PATHS, NAV_ITEMS } from '../navigation/navigationConfig';

const APPLICATION_NAME = 'Semantix';
const NOT_FOUND_TITLE = `Page not found | ${APPLICATION_NAME}`;

function titleForPath(pathname: string): string {
  const canonicalPathname =
    pathname === APP_PATHS.benchmarks ? APP_PATHS.evaluations : pathname;
  const route = NAV_ITEMS.find(({ to }) =>
    to === '/'
      ? canonicalPathname === to
      : canonicalPathname === to || canonicalPathname.startsWith(`${to}/`),
  );

  return route === undefined ? NOT_FOUND_TITLE : `${route.label} | ${APPLICATION_NAME}`;
}

export function useRouteAccessibility(mainRef: RefObject<HTMLElement | null>): void {
  const { pathname } = useLocation();
  const navigationType = useNavigationType();
  const previousPathname = useRef(pathname);

  useEffect(() => {
    document.title = titleForPath(pathname);
  }, [pathname]);

  useEffect(() => {
    const previousPath = previousPathname.current;
    const pathChanged = previousPath !== pathname;
    const isCompatibilityRedirect =
      previousPath === APP_PATHS.benchmarks &&
      pathname === APP_PATHS.evaluations &&
      navigationType === 'REPLACE';
    previousPathname.current = pathname;

    if (pathChanged && (navigationType === 'PUSH' || isCompatibilityRedirect)) {
      mainRef.current?.focus({ preventScroll: true });
      window.scrollTo({
        behavior: 'auto',
        left: 0,
        top: 0,
      });
    }
  }, [mainRef, navigationType, pathname]);
}
