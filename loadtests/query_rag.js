import { check, sleep } from "k6";
import { baseUrl, login, postQuery, jsonBody, requireStatus } from "./lib.js";

export const options = {
  vus: Number(__ENV.VUS || 3),
  duration: __ENV.DURATION || "1m",
  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<8000"],
  },
};

const payload = {
  question:
    __ENV.QUESTION ||
    "What does our escalation policy say for P1 incidents?",
  top_k: Number(__ENV.TOP_K || 5),
  search_mode: __ENV.SEARCH_MODE || "hybrid",
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
  const res = postQuery(data.url, data.token, payload, {
    scenario: "rag_query",
  });
  requireStatus(res, 200, "rag query returned 200");

  const body = jsonBody(res);
  check(body, {
    "rag body parsed": (b) => b !== null,
    "rag answer present": (b) => Boolean(b && b.answer),
    "rag no pending sql": (b) => !b?.pending_sql,
  });

  sleep(1);
}
