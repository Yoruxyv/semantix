import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type JSX, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router";

import { APP_PATHS } from "@/app/navigation/navigationConfig";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { canDeleteCacheEntries } from "@/features/auth/permissions";
import { MarkdownContent } from "@/shared/components/markdown/MarkdownContent";
import { Alert, Button, InlineConfirmation, PageHeader } from "@/shared/components/ui";
import {
  formatCompactDuration,
  formatCount,
  formatTimestamp,
} from "@/shared/lib/formatters";
import { dataFromApiResult } from "@/shared/query/apiResult";
import { cacheEntryKeys } from "@/shared/query/queryKeys";

import { deleteCacheEntry, getCacheEntry } from "../api/cacheApi";
import { useCacheControl } from "../hooks/useCacheControl";

const CACHE_KEY_PATTERN = /^[a-f0-9]{64}$/;
const UNAVAILABLE_MESSAGE =
  "This cache entry could not be found or is no longer available.";

function shortCacheKey(cacheKey: string): string {
  return `${cacheKey.slice(0, 10)}...${cacheKey.slice(-6)}`;
}

function returnSearchFromState(state: unknown): string {
  if (
    typeof state === "object" &&
    state !== null &&
    "cacheReturnSearch" in state &&
    typeof state.cacheReturnSearch === "string" &&
    (state.cacheReturnSearch === "" || state.cacheReturnSearch.startsWith("?"))
  ) {
    return state.cacheReturnSearch;
  }
  return "";
}

function DetailItem({
  children,
  className = "",
  label,
}: Readonly<{
  children: ReactNode;
  className?: string;
  label: string;
}>): JSX.Element {
  return (
    <div className={`min-w-0 ${className}`}>
      <dt className="ui-label text-(--text-faint)">{label}</dt>
      <dd className="font-data mt-2 wrap-break-word text-[11px]/5 text-(--text-soft)">
        {children}
      </dd>
    </div>
  );
}

export function CacheEntryDetailPage(): JSX.Element {
  const { cacheKey = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const auth = useAuth();
  const { refreshCacheState } = useCacheControl();
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const isValidKey = CACHE_KEY_PATTERN.test(cacheKey);
  const returnTo = `${APP_PATHS.cache}${returnSearchFromState(location.state)}`;
  const canDelete = canDeleteCacheEntries(auth.status, auth.session);

  const entryQuery = useQuery({
    queryKey: cacheEntryKeys.detail(cacheKey),
    queryFn: async ({ signal }) =>
      dataFromApiResult(await getCacheEntry(cacheKey, signal)),
    enabled: isValidKey,
    staleTime: 20_000,
    gcTime: 5 * 60_000,
  });
  const deleteMutation = useMutation({
    mutationFn: async () =>
      dataFromApiResult(await deleteCacheEntry(cacheKey)),
  });

  async function copyCacheKey(): Promise<void> {
    try {
      await navigator.clipboard.writeText(cacheKey);
      setCopyStatus("Cache key copied.");
    } catch {
      setCopyStatus("Cache key could not be copied.");
    }
  }

  async function confirmEntryDeletion(): Promise<void> {
    setDeleteError(null);
    try {
      await deleteMutation.mutateAsync();
      queryClient.removeQueries({
        queryKey: cacheEntryKeys.detail(cacheKey),
        exact: true,
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: cacheEntryKeys.lists() }),
        refreshCacheState(false),
      ]);
      void navigate(returnTo, {
        replace: true,
        state: { cacheMutationNotice: "Cache entry deleted." },
      });
    } catch {
      setDeleteError("The cache entry was not deleted.");
    }
  }

  const entry = entryQuery.data;

  return (
    <section aria-labelledby="cache-entry-detail-heading">
      <Link
        className="ui-label inline-flex min-h-10 items-center border-b border-(--teal) px-1 py-2 text-(--teal) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--teal)"
        to={returnTo}
      >
        Back to Cache
      </Link>

      <PageHeader
        className="my-8"
        description="Authorized live-cache evidence is best-effort and may disappear after expiry, eviction, deletion, restart, or an embedding-space change."
        eyebrow="Live cache evidence"
        headingId="cache-entry-detail-heading"
        title="Cache entry detail"
      />

      {!isValidKey && (
        <Alert
          className="border-l border-(--coral) pl-4 text-sm/6"
          role="alert"
          tone="error"
        >
          {UNAVAILABLE_MESSAGE}
        </Alert>
      )}

      {isValidKey && entryQuery.isPending && (
        <output
          aria-live="polite"
          className="font-data block animate-pulse border-y border-(--hairline) py-8 text-[11px] text-(--text-faint)"
        >
          Loading cache entry details...
        </output>
      )}

      {isValidKey && entryQuery.isError && (
        <Alert
          action={
            <Button
              className="text-(--teal) focus-visible:outline-(--teal)"
              variant="link"
              onClick={() => void entryQuery.refetch()}
            >
              Try again
            </Button>
          }
          className="border-l border-(--coral) pl-4 text-sm/6"
          role="alert"
          tone="error"
        >
          {UNAVAILABLE_MESSAGE}
        </Alert>
      )}

      {entry !== undefined && (
        <article className="min-w-0 border-t border-(--hairline) pt-7">
          <header className="flex flex-wrap items-start justify-between gap-5">
            <div className="min-w-0">
              <p className="ui-label text-(--teal)">
                {entry.is_expired ? "Expired" : "Active"}
              </p>
              <h2 className="font-display mt-2 wrap-break-word text-2xl italic">
                {entry.prompt}
              </h2>
            </div>
            <Button
              className="border-(--hairline) text-(--text-soft) hover:border-(--teal) hover:text-(--teal)"
              size="compact"
              onClick={() => void copyCacheKey()}
            >
              Copy cache key
            </Button>
          </header>

          <output
            aria-live="polite"
            className="font-data mt-3 block min-h-5 text-[11px] text-(--text-faint)"
          >
            {copyStatus}
          </output>

          <dl
            className="mt-5 grid min-w-0 gap-5 lg:grid-cols-2"
            data-cache-entry-detail-grid
          >
            <DetailItem className="lg:col-span-2" label="Cache key">
              <code className="break-all">{entry.cache_key}</code>
            </DetailItem>
            <DetailItem label="Namespace">{entry.namespace}</DetailItem>
            <DetailItem label="Status">
              {entry.is_expired ? "Expired" : "Active"}
            </DetailItem>
            <DetailItem label="Created">
              {formatTimestamp(entry.created_at)}
            </DetailItem>
            <DetailItem label="Expires">
              {formatTimestamp(entry.expires_at, "No expiry")}
            </DetailItem>
            <DetailItem label="TTL remaining">
              {formatCompactDuration(entry.remaining_ttl_seconds, {
                fallback: "No expiry",
              })}
            </DetailItem>
            <DetailItem label="Entry hits">
              {formatCount(entry.hit_count)}
            </DetailItem>
            <DetailItem label="Last accessed">
              {formatTimestamp(entry.last_accessed_at)}
            </DetailItem>
            <DetailItem label="Recency rank">
              #{formatCount(entry.recency_rank)}
            </DetailItem>
            <DetailItem className="lg:col-span-2" label="Response preview">
              <MarkdownContent
                className="min-w-0 text-sm text-(--text-muted)"
                density="compact"
                markdown={entry.response_preview}
              />
            </DetailItem>
          </dl>

          {canDelete && !confirmDelete && (
            <Button
              className="mt-8"
              variant="danger"
              onClick={() => setConfirmDelete(true)}
            >
              Delete cache entry
            </Button>
          )}

          {canDelete && confirmDelete && (
            <InlineConfirmation
              ariaLabel={`Confirm deletion of cache entry ${shortCacheKey(entry.cache_key)} in namespace ${entry.namespace}`}
              className="mt-8"
              confirmLabel="Confirm delete"
              isPending={deleteMutation.isPending}
              message={
                <>
                  Delete <code>{shortCacheKey(entry.cache_key)}</code> from
                  namespace <code>{entry.namespace}</code>? Cached responses
                  using it will no longer be reused.
                </>
              }
              pendingLabel="Deleting"
              onCancel={() => setConfirmDelete(false)}
              onConfirm={() => void confirmEntryDeletion()}
            />
          )}

          {deleteError !== null && (
            <Alert
              className="mt-5 border-l border-(--coral) pl-4 text-sm/6"
              role="alert"
              tone="error"
            >
              {deleteError}
            </Alert>
          )}
        </article>
      )}
    </section>
  );
}
