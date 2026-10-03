import { useContext } from 'react';

import { MonitorContext, type MonitorContextValue } from '../context/monitorState';

export function useMonitor(): MonitorContextValue {
  const context = useContext(MonitorContext);

  if (context === null) {
    throw new Error('useMonitor must be used within a MonitorProvider');
  }

  return context;
}
