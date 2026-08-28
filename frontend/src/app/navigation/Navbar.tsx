import { useEffect, useRef, useState, type JSX } from 'react';
import { NavLink, useLocation } from 'react-router';

import { useAuth } from '@/features/auth/hooks/useAuth';
import { canAccessGlobalMetrics } from '@/features/auth/permissions';

import { preloadRouteModule } from '../router/routes';
import { APP_PATHS, NAV_ITEMS } from './navigationConfig';
import { SessionUptime } from './SessionUptime';

const EXPANDED_NAV_MIN_WIDTH = 1_024;

function navClass(isActive: boolean): string {
  const tone = isActive
    ? 'border-l-[var(--gold)] bg-[rgba(212,161,90,0.08)] text-[var(--gold)] lg:border-b-[var(--gold)] lg:border-l-transparent'
    : 'border-l-transparent text-[var(--text-muted)] hover:bg-[rgba(234,230,221,0.04)] hover:text-[var(--text)] lg:border-b-transparent';

  return `ui-label block border-b border-b-[var(--hairline)] border-l-2 px-3 py-3 transition-colors motion-reduce:transition-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--gold)] lg:border-b lg:border-l-0 lg:py-2 ${tone}`;
}

function preloadRoute(pathname: string): void {
  void preloadRouteModule(pathname).catch(() => undefined);
}

export function Navbar(): JSX.Element {
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const navigationRef = useRef<HTMLElement>(null);
  const { pathname } = useLocation();
  const { session, status } = useAuth();
  const canViewMetrics = canAccessGlobalMetrics(status, session);
  const visibleNavItems = NAV_ITEMS.filter(
    (item) => item.to !== APP_PATHS.observability || canViewMetrics,
  );

  useEffect(() => {
    setIsMenuOpen(false);
  }, [pathname]);

  useEffect(() => {
    function closeExpandedMenu(): void {
      if (window.innerWidth >= EXPANDED_NAV_MIN_WIDTH) {
        setIsMenuOpen(false);
      }
    }

    window.addEventListener('resize', closeExpandedMenu);
    return () => window.removeEventListener('resize', closeExpandedMenu);
  }, []);

  useEffect(() => {
    if (!isMenuOpen) {
      return undefined;
    }

    function closeOnEscape(event: KeyboardEvent): void {
      if (event.key !== 'Escape') {
        return;
      }

      event.preventDefault();
      if (
        document.activeElement !== null &&
        navigationRef.current?.contains(document.activeElement)
      ) {
        menuButtonRef.current?.focus();
      }
      setIsMenuOpen(false);
    }

    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [isMenuOpen]);

  return (
    <header className="sticky top-0 z-30 border-b border-(--hairline) bg-(--ink) py-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3 lg:grid lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] lg:gap-x-6">
        <div className="min-w-0 flex-1 lg:col-start-1 lg:row-start-1 lg:min-w-48 lg:flex-none">
          <p className="ui-label text-(--gold)">Semantix</p>
          <p className="font-display mt-1 hidden text-lg italic text-(--text-soft) sm:block">
            Semantic cache laboratory
          </p>
        </div>

        <SessionUptime className="order-1 lg:col-start-3 lg:row-start-1 lg:justify-self-end" />

        <button
          ref={menuButtonRef}
          aria-controls="primary-navigation"
          aria-expanded={isMenuOpen}
          aria-label={isMenuOpen ? 'Close primary menu' : 'Open primary menu'}
          className="order-2 flex size-11 shrink-0 items-center justify-center border border-(--hairline) bg-(--surface) text-(--gold) transition-colors motion-reduce:transition-none hover:border-(--gold) focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-(--gold) lg:hidden"
          type="button"
          onClick={() => setIsMenuOpen((current) => !current)}
        >
          <span aria-hidden="true" className="flex w-5 flex-col items-stretch gap-1.5">
            <span
              className={`block h-px bg-current transition-transform motion-reduce:transition-none ${
                isMenuOpen ? 'translate-y-[7px] rotate-45' : ''
              }`}
            />
            <span
              className={`block h-px bg-current transition-opacity motion-reduce:transition-none ${
                isMenuOpen ? 'opacity-0' : ''
              }`}
            />
            <span
              className={`block h-px bg-current transition-transform motion-reduce:transition-none ${
                isMenuOpen ? 'translate-y-[-7px] -rotate-45' : ''
              }`}
            />
          </span>
        </button>

        <nav
          ref={navigationRef}
          aria-label="Primary navigation"
          className={`${isMenuOpen ? 'block' : 'hidden'} order-3 w-full border border-(--hairline) bg-(--surface) p-1 lg:col-start-2 lg:row-start-1 lg:block lg:w-fit lg:justify-self-center`}
          id="primary-navigation"
        >
          <div className="flex flex-col lg:flex-row lg:items-center lg:gap-1">
            {visibleNavItems.map((item) => (
              <NavLink
                end={item.to === APP_PATHS.monitor}
                key={item.to}
                className={({ isActive }) => navClass(isActive)}
                to={item.to}
                onFocus={() => preloadRoute(item.to)}
                onPointerEnter={() => preloadRoute(item.to)}
                onClick={() => setIsMenuOpen(false)}
              >
                {item.label}
              </NavLink>
            ))}
          </div>
        </nav>
      </div>
    </header>
  );
}
