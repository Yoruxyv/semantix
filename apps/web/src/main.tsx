import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import App from './App';
import { AppErrorBoundary } from './app/errors/AppErrorBoundary';
import { AppBrowserRouter } from './app/router/AppBrowserRouter';
import './index.css';

const rootElement = document.getElementById('root');

if (rootElement === null) {
  throw new Error('Root element was not found');
}

createRoot(rootElement).render(
  <StrictMode>
    <AppErrorBoundary>
      <AppBrowserRouter>
        <App />
      </AppBrowserRouter>
    </AppErrorBoundary>
  </StrictMode>,
);
