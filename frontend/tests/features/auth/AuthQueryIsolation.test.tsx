import { useQuery } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useContext, type JSX } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { QueryTestProvider } from "../QueryTestProvider";
import { createTestQueryClient } from "../queryClient";
import {
  getAuthConfig,
  getAuthSession,
} from "@/features/auth/api/authApi";
import {
  AuthContext,
} from "@/features/auth/context/AuthContext";
import { AuthProvider } from "@/features/auth/context/AuthProvider";
import {
  getAuthToken,
  setAuthToken,
} from "@/shared/api/authToken";
import {
  benchmarkDatasetKeys,
  cacheEntryKeys,
  runtimeDiagnosticsKeys,
  runtimeMetricsKeys,
} from "@/shared/query/queryKeys";

function ProtectedDataProbe(): JSX.Element {
  const auth = useContext(AuthContext);
  if (auth === null) {
    throw new Error("Auth context is unavailable");
  }
  const protectedQuery = useQuery({
    queryKey: runtimeMetricsKeys.live(),
    queryFn: async () => "replacement metrics",
    enabled: false,
  });

  return (
    <>
      <output aria-label="Authentication status">{auth.status}</output>
      <output aria-label="Authentication error">
        {auth.error ?? "none"}
      </output>
      <output aria-label="Authentication lock">
        {auth.lockedUntil ?? "none"}
      </output>
      <output aria-label="Protected metrics">
        {protectedQuery.data ?? "empty"}
      </output>
      <button type="button" onClick={async () => auth.authenticate("new-token")}>
        Authenticate test identity
      </button>
      <button type="button" onClick={auth.logout}>
        Logout test identity
      </button>
      <button type="button" onClick={auth.retryAccessPolicy}>
        Retry authentication bootstrap
      </button>
    </>
  );
}

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  vi.clearAllMocks();
});

describe("authentication query isolation", () => {
  it("removes protected data when identity changes and on logout", async () => {
    vi.mocked(getAuthConfig).mockResolvedValue({
      ok: true,
      data: { authentication_required: true },
    });
    vi.mocked(getAuthSession).mockResolvedValue({
      ok: true,
      data: {
        name: "new-principal",
        role: "admin",
        namespaces: ["*"],
      },
    });
    const queryClient = createTestQueryClient();
    const cacheKey = cacheEntryKeys.list({
      offset: 0,
      limit: 10,
      namespace: "",
      search: "",
      sort: "newest",
    });
    queryClient.setQueryData(runtimeMetricsKeys.live(), "old metrics");
    queryClient.setQueryData(runtimeDiagnosticsKeys.live(), "old diagnostics");
    queryClient.setQueryData(cacheKey, "old cache entries");
    queryClient.setQueryData(
      benchmarkDatasetKeys.catalog(),
      "old datasets",
    );
    const persistedKey = benchmarkDatasetKeys.persistedDetail(
      "123e4567-e89b-42d3-a456-426614174000",
    );
    queryClient.setQueryData(persistedKey, "old persisted detail");
    queryClient.setQueryData(["public-preference"], "preserve me");

    render(
      <QueryTestProvider client={queryClient}>
        <AuthProvider>
          <ProtectedDataProbe />
        </AuthProvider>
      </QueryTestProvider>,
    );
    expect(screen.getByLabelText("Protected metrics").textContent).toBe(
      "old metrics",
    );
    await screen.findByText("unauthenticated");

    fireEvent.click(screen.getByRole("button", { name: "Authenticate test identity" }));

    await screen.findByText("authenticated");
    expect(screen.getByLabelText("Protected metrics").textContent).toBe(
      "empty",
    );
    expect(queryClient.getQueryData(cacheKey)).toBeUndefined();
    expect(
      queryClient.getQueryData(benchmarkDatasetKeys.catalog()),
    ).toBeUndefined();
    expect(queryClient.getQueryData(persistedKey)).toBeUndefined();
    expect(
      queryClient.getQueryData(runtimeDiagnosticsKeys.live()),
    ).toBeUndefined();
    expect(queryClient.getQueryData(["public-preference"])).toBe(
      "preserve me",
    );

    act(() => {
      queryClient.setQueryData(runtimeMetricsKeys.live(), "second identity");
    });
    await waitFor(() =>
      expect(screen.getByLabelText("Protected metrics").textContent).toBe(
        "second identity",
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Logout test identity" }));
    await screen.findByText("unauthenticated");
    expect(screen.getByLabelText("Protected metrics").textContent).toBe(
      "empty",
    );
    expect(getAuthToken()).toBeNull();
  });

  it("removes protected data when authentication becomes disabled", async () => {
    vi.mocked(getAuthConfig).mockResolvedValue({
      ok: true,
      data: { authentication_required: false },
    });
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(runtimeMetricsKeys.live(), "old metrics");

    render(
      <QueryTestProvider client={queryClient}>
        <AuthProvider>
          <ProtectedDataProbe />
        </AuthProvider>
      </QueryTestProvider>,
    );

    await screen.findByText("disabled");
    expect(screen.getByLabelText("Protected metrics").textContent).toBe(
      "empty",
    );
    expect(
      queryClient.getQueryData(runtimeMetricsKeys.live()),
    ).toBeUndefined();
  });

  it("distinguishes policy failure and retries the configuration request", async () => {
    vi.mocked(getAuthConfig)
      .mockResolvedValueOnce({
        ok: false,
        error: {
          code: "rate_limit_exceeded",
          detail: "Too many requests. Please try again later.",
          status: 429,
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: { authentication_required: false },
      });
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(runtimeMetricsKeys.live(), "private metrics");

    render(
      <QueryTestProvider client={queryClient}>
        <AuthProvider>
          <ProtectedDataProbe />
        </AuthProvider>
      </QueryTestProvider>,
    );

    await screen.findByText("error");
    expect(screen.getByLabelText("Authentication error").textContent).toBe(
      "Access policy unavailable. Semantix could not determine the current " +
        "authentication policy. Please wait a moment and try again.",
    );
    expect(screen.getByLabelText("Protected metrics").textContent).toBe(
      "empty",
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "Retry authentication bootstrap",
      }),
    );

    await screen.findByText("disabled");
    expect(getAuthConfig).toHaveBeenCalledTimes(2);
  });

  it("restores a stored session repeatedly without an authentication error", async () => {
    setAuthToken("stored-token");
    vi.mocked(getAuthConfig).mockResolvedValue({
      ok: true,
      data: { authentication_required: true },
    });
    vi.mocked(getAuthSession).mockResolvedValue({
      ok: true,
      data: {
        name: "restored-principal",
        role: "viewer",
        namespaces: ["team-a"],
      },
    });

    const firstRender = render(
      <QueryTestProvider client={createTestQueryClient()}>
        <AuthProvider>
          <ProtectedDataProbe />
        </AuthProvider>
      </QueryTestProvider>,
    );

    await screen.findByText("authenticated");
    expect(screen.getByLabelText("Authentication error").textContent).toBe(
      "none",
    );
    firstRender.unmount();

    render(
      <QueryTestProvider client={createTestQueryClient()}>
        <AuthProvider>
          <ProtectedDataProbe />
        </AuthProvider>
      </QueryTestProvider>,
    );

    await screen.findByText("authenticated");
    expect(screen.getByLabelText("Authentication error").textContent).toBe(
      "none",
    );
    expect(getAuthSession).toHaveBeenCalledTimes(2);
    expect(getAuthToken()).toBe("stored-token");
  });

  it("clears a stored token only when the credential is rejected", async () => {
    setAuthToken("rejected-token");
    vi.mocked(getAuthConfig).mockResolvedValue({
      ok: true,
      data: { authentication_required: true },
    });
    vi.mocked(getAuthSession).mockResolvedValue({
      ok: false,
      error: {
        code: "authentication_required",
        detail: "A valid bearer token is required.",
        status: 401,
      },
    });

    render(
      <QueryTestProvider client={createTestQueryClient()}>
        <AuthProvider>
          <ProtectedDataProbe />
        </AuthProvider>
      </QueryTestProvider>,
    );

    await screen.findByText("unauthenticated");
    expect(screen.getByLabelText("Authentication error").textContent).toBe(
      "The access token was rejected.",
    );
    expect(getAuthToken()).toBeNull();
  });

  it.each([
    ["network_error", null],
    ["invalid_response", 502],
    ["invalid_error_response", 502],
    ["internal_error", 500],
    ["rate_limit_exceeded", 429],
  ] as const)(
    "preserves a token and retries after transient %s session failure",
    async (errorCode, status) => {
      setAuthToken("potentially-valid-token");
      vi.mocked(getAuthConfig).mockResolvedValue({
        ok: true,
        data: { authentication_required: true },
      });
      vi.mocked(getAuthSession)
        .mockResolvedValueOnce({
          ok: false,
          error: {
            code: errorCode,
            detail: "Temporary session verification failure.",
            status,
          },
        })
        .mockResolvedValueOnce({
          ok: true,
          data: {
            name: "restored-principal",
            role: "operator",
            namespaces: ["team-a"],
          },
        });
      const queryClient = createTestQueryClient();
      queryClient.setQueryData(runtimeMetricsKeys.live(), "private metrics");

      render(
        <QueryTestProvider client={queryClient}>
          <AuthProvider>
            <ProtectedDataProbe />
          </AuthProvider>
        </QueryTestProvider>,
      );

      await screen.findByText("session-error");
      expect(screen.getByLabelText("Authentication error").textContent).toBe(
        "Session verification unavailable. Semantix could not verify the " +
          "current authentication session. Please wait a moment and try again.",
      );
      expect(getAuthToken()).toBe("potentially-valid-token");
      expect(screen.getByLabelText("Protected metrics").textContent).toBe(
        "empty",
      );

      fireEvent.click(
        screen.getByRole("button", {
          name: "Retry authentication bootstrap",
        }),
      );

      await screen.findByText("authenticated");
      expect(getAuthSession).toHaveBeenCalledTimes(2);
      expect(getAuthToken()).toBe("potentially-valid-token");
    },
  );

  it("clears protected data and records backend lockout expiration", async () => {
    vi.mocked(getAuthConfig).mockResolvedValue({
      ok: true,
      data: { authentication_required: true },
    });
    vi.mocked(getAuthSession).mockResolvedValue({
      ok: false,
      error: {
        code: "authentication_temporarily_locked",
        detail:
          "Too many failed authentication attempts. Please try again later.",
        retryAfterSeconds: 30,
        status: 429,
      },
    });
    const queryClient = createTestQueryClient();
    queryClient.setQueryData(runtimeMetricsKeys.live(), "private metrics");
    const beforeAuthentication = Date.now();

    render(
      <QueryTestProvider client={queryClient}>
        <AuthProvider>
          <ProtectedDataProbe />
        </AuthProvider>
      </QueryTestProvider>,
    );
    await screen.findByText("unauthenticated");

    fireEvent.click(
      screen.getByRole("button", {
        name: "Authenticate test identity",
      }),
    );

    await screen.findByText("Too many failed authentication attempts.");
    expect(screen.getByLabelText("Protected metrics").textContent).toBe(
      "empty",
    );
    const lockedUntil = Number(
      screen.getByLabelText("Authentication lock").textContent,
    );
    expect(lockedUntil).toBeGreaterThanOrEqual(
      beforeAuthentication + 30_000,
    );
    expect(getAuthToken()).toBe("new-token");
  });
});
