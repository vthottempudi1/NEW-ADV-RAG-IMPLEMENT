import { check, sleep } from "k6";
import { baseUrl, login, completeSqlFlow } from "./lib.js";

export const options = {
  vus: Number(__ENV.VUS || 1),
  duration: __ENV.DURATION || "45s",
  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<10000"],
  },
};

const payload = {
  question:
    __ENV.QUESTION ||
    "How many P1 incidents were resolved last quarter?",
  top_k: Number(__ENV.TOP_K || 5),
  search_mode: __ENV.SEARCH_MODE || "auto",
  enable_rerank: true,
  enable_hyde: false,
  enable_crag: true,
  enable_self_reflective: false,
};

export function setup() {
  const url = baseUrl();
  const session = login(url);
  return { url, token: session.token };
}

export default function (data) {
  const result = completeSqlFlow(data.url, data.token, payload, {
    scenario: "sql_query",
  });

  const finalJson = result.executeJson || result.queryJson;
  check(finalJson, {
    "sql final body parsed": (b) => b !== null,
    "sql final route exists": (b) => Boolean(b?.metadata?.route),
    "sql answer or pending returned": (b) => Boolean(b?.answer || b?.pending_sql),
  });

  sleep(1);
}
