import { useEffect, useState, type JSX } from 'react';

import { formatClockDuration } from '@/shared/lib/formatters';

const SESSION_STARTED_AT = Date.now();

interface SessionUptimeProps {
  className?: string;
}

export function SessionUptime({
  className = '',
}: Readonly<SessionUptimeProps>): JSX.Element {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setElapsed(Date.now() - SESSION_STARTED_AT);
    }, 1_000);

    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className={`${className} shrink-0 text-right`}>
      <p className="ui-label text-(--text-faint)">Session uptime</p>
      <time className="font-data mt-1 block text-[10px] text-(--text-soft)">
        {formatClockDuration(elapsed)}
      </time>
    </div>
  );
}
