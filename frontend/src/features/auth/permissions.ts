import type { AuthContextValue } from "./context/AuthContext";
import type { AuthSession } from "./types";

export function canAccessGlobalMetrics(
  status: AuthContextValue["status"],
  session: AuthSession | null,
): boolean {
  if (status === "disabled") {
    return true;
  }

  return (
    status === "authenticated" &&
    session?.role === "admin" &&
    session.namespaces.includes("*")
  );
}

export function canRunBenchmarks(
  status: AuthContextValue["status"],
  session: AuthSession | null,
): boolean {
  return canSubmitQueries(status, session);
}

export function canSubmitQueries(
  status: AuthContextValue["status"],
  session: AuthSession | null,
): boolean {
  if (status === "disabled") {
    return true;
  }

  return (
    status === "authenticated" &&
    (session?.role === "operator" || session?.role === "admin")
  );
}

export function canApplyGlobalThreshold(
  status: AuthContextValue["status"],
  session: AuthSession | null,
): boolean {
  return canAccessGlobalMetrics(status, session);
}

export function canPersistEvaluationDatasets(
  status: AuthContextValue["status"],
  session: AuthSession | null,
): boolean {
  return canRunBenchmarks(status, session);
}

export function canDeleteEvaluationDatasets(
  status: AuthContextValue["status"],
  session: AuthSession | null,
): boolean {
  if (status === "disabled") {
    return true;
  }

  return status === "authenticated" && session?.role === "admin";
}

export function canDeleteCacheEntries(
  status: AuthContextValue["status"],
  session: AuthSession | null,
): boolean {
  return canDeleteEvaluationDatasets(status, session);
}

export function canDeleteEvaluationRunHistory(
  status: AuthContextValue["status"],
  session: AuthSession | null,
): boolean {
  return canDeleteEvaluationDatasets(status, session);
}
