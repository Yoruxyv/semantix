import { Link } from 'react-router';

import type { JSX } from 'react';

export function NotFoundPage(): JSX.Element {
  return (
    <section aria-labelledby="not-found-heading" className="py-16">
      <p className="font-data text-sm text-(--coral-text)">404</p>
      <h1 className="font-display mt-2 text-4xl italic" id="not-found-heading">
        Signal not found
      </h1>
      <p className="mt-4 max-w-xl text-sm/6  text-(--text-muted)">
        This route is outside the current Semantix field map.
      </p>
      <Link
        className="ui-label mt-8 inline-block border-b border-(--gold) pb-1 text-(--gold) focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-(--gold)"
        to="/"
      >
        Return to Monitor
      </Link>
    </section>
  );
}
