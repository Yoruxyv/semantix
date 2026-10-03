import { Component, type ErrorInfo, type ReactNode, type JSX } from 'react';

export interface AppErrorReport {
  readonly componentStackAvailable: boolean;
  readonly errorName: string;
}

interface AppErrorBoundaryProps {
  readonly children: ReactNode;
  readonly onError?: (report: AppErrorReport) => void;
  readonly reloadApplication?: () => void;
}

interface AppErrorBoundaryState {
  readonly failed: boolean;
}

function reportAppError(report: AppErrorReport): void {
  console.error('Unexpected application render failure', report);
}

function reloadApplication(): void {
  window.location.reload();
}

export class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  public state: AppErrorBoundaryState = { failed: false };

  public static getDerivedStateFromError(): AppErrorBoundaryState {
    return { failed: true };
  }

  public componentDidCatch(error: unknown, info: ErrorInfo): void {
    const errorName = error instanceof Error ? error.name : 'UnknownError';
    (this.props.onError ?? reportAppError)({
      componentStackAvailable: info.componentStack !== null,
      errorName,
    });
  }

  public render(): JSX.Element {
    if (!this.state.failed) {
      return <>{this.props.children}</>;
    }

    return (
      <main className="grid min-h-screen place-items-center bg-(--ink) px-6 text-(--text)">
        <section
          aria-labelledby="app-failure-heading"
          className="max-w-lg border border-(--line) bg-(--panel) p-8"
        >
          <p className="ui-label text-(--gold)">Application recovery</p>
          <h1 className="font-display mt-3 text-3xl italic" id="app-failure-heading">
            Semantix could not finish loading
          </h1>
          <p className="mt-4 text-sm/6 text-(--text-muted)">
            An unexpected interface error occurred. Reload the application to try again.
          </p>
          <button
            className="ui-label mt-6 border border-(--gold) px-4 py-3 text-(--gold) focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-(--gold)"
            type="button"
            onClick={this.props.reloadApplication ?? reloadApplication}
          >
            Reload application
          </button>
        </section>
      </main>
    );
  }
}
