import http from "k6/http";
import { sleep } from "k6";
import { Counter } from "k6/metrics";

const base = __ENV.BASE_URL;
const token = __ENV.SEMANTIX_TOKEN;
const namespace = __ENV.SEMANTIX_NAMESPACE || "phase13";
const profile = __ENV.PROFILE || "cache-heavy";
const runId = __ENV.RUN_ID || "manual";
const vus = Number(__ENV.VUS || "50");
const duration = __ENV.DURATION || "60s";
const burst = profile === "cold-burst";

if (__ENV.LOAD_ACKNOWLEDGE_PROVIDER_CALLS !== "true" || !base || !token) {
  throw new Error("Use a disposable mock-provider stack and set BASE_URL, SEMANTIX_TOKEN, and LOAD_ACKNOWLEDGE_PROVIDER_CALLS=true");
}
if (!["cache-heavy", "generation-heavy", "mixed-policy", "cold-burst"].includes(profile)) {
  throw new Error(`Unknown capacity profile: ${profile}`);
}
if (!Number.isInteger(vus) || vus < 1) {
  throw new Error("VUS must be a positive integer");
}

const status2xx = new Counter("phase13_status_2xx");
const status4xx = new Counter("phase13_status_4xx");
const status429 = new Counter("phase13_status_429");
const status5xx = new Counter("phase13_status_5xx");
const status502 = new Counter("phase13_status_502");
const status503 = new Counter("phase13_status_503");
const status504 = new Counter("phase13_status_504");
const transportErrors = new Counter("phase13_transport_errors");
const hits = new Counter("phase13_cache_hits");
const misses = new Counter("phase13_cache_misses");
const providerCalls = new Counter("phase13_provider_calls");
const coalesced = new Counter("phase13_coalesced_responses");

export const options = {
  scenarios: {
    capacity: burst
      ? { executor: "per-vu-iterations", vus, iterations: 1, maxDuration: "2m" }
      : { executor: "constant-vus", vus, duration, gracefulStop: "30s" },
  },
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
  noConnectionReuse: false,
};

const policies = {
  normal: { cache_enabled: true, cache_read_enabled: true, cache_write_enabled: true, private: false },
  read_only: { cache_enabled: true, cache_read_enabled: true, cache_write_enabled: false, private: false },
  refresh: { cache_enabled: true, cache_read_enabled: false, cache_write_enabled: true, private: false },
  bypass: { cache_enabled: false, cache_read_enabled: false, cache_write_enabled: false, private: false },
  private: { cache_enabled: false, cache_read_enabled: false, cache_write_enabled: false, private: true },
};

export default function () {
  const slot = (__ITER + __VU) % 10;
  let prompt;
  let policy = policies.normal;
  if (burst) {
    prompt = `Phase 13 cold identical ${runId}`;
  } else if (profile === "cache-heavy") {
    prompt = slot < 8
      ? `Phase 13 repeated ${runId} ${slot % 8}`
      : `Phase 13 unique ${runId} ${__VU} ${__ITER}`;
  } else if (profile === "generation-heavy") {
    prompt = slot === 0
      ? `Phase 13 repeated ${runId} 0`
      : `Phase 13 unique ${runId} ${__VU} ${__ITER}`;
  } else {
    policy = slot < 6 ? policies.normal
      : slot === 6 ? policies.read_only
      : slot === 7 ? policies.refresh
      : slot === 8 ? policies.bypass : policies.private;
    prompt = slot < 4 || slot === 6
      ? `Phase 13 repeated ${runId} ${slot % 4}`
      : `Phase 13 unique ${runId} ${__VU} ${__ITER}`;
  }

  const response = http.post(`${base}/api/v1/query`, JSON.stringify({
    prompt, namespace, ...policy,
  }), {
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    timeout: "30s",
    tags: { profile },
  });
  if (response.status >= 200 && response.status < 300) status2xx.add(1);
  else if (response.status === 429) { status4xx.add(1); status429.add(1); }
  else if (response.status >= 400 && response.status < 500) status4xx.add(1);
  else if (response.status >= 500) {
    status5xx.add(1);
    if (response.status === 502) status502.add(1);
    if (response.status === 503) status503.add(1);
    if (response.status === 504) status504.add(1);
  }
  else transportErrors.add(1);

  if (response.status === 200) {
    const body = response.json();
    (body.cache_hit ? hits : misses).add(1);
    if (body.provider_called) providerCalls.add(1);
    if (!body.cache_hit && !body.provider_called) coalesced.add(1);
  }
  if (!burst) sleep(2 + ((__VU + __ITER) % 3));
}
