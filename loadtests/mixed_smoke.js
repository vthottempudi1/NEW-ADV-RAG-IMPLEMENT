import { check, sleep } from "k6";
import {
  baseUrl,
  login,
  postQuery,
  jsonBody,
  requireStatus,
  completeSqlFlow,
} from "./lib.js";

export const options = {
  scenarios: {
    rag: {
      executor: "constant-vus",
      vus: Number(__ENV.RAG_VUS || 2),
      duration: __ENV.DURATION || "1m",
      exec: "runRag",
    },
    sql: {
      executor: "constant-vus",
      vus: Number(__ENV.SQL_VUS || 1),
      duration: __ENV.DURATION || "1m",
      exec: "runSql",
      startTime: "5s",
    },
    hybrid: {
      executor: "constant-vus",
      vus: Number(__ENV.HYBRID_VUS || 1),
      duration: __ENV.DURATION || "1m",
      exec: "runHybrid",
      startTime: "10s",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<12000"],
  },
};

const ragPayload = {
  question: "What does our escalation policy say for P1 incidents?",
  top_k: 5,
  search_mode: "hybrid",
  enable_rerank: true,
  enable_hyde: false,
  enable_crag: true,
  enable_self_reflective: false,
};

const sqlPayload = {
  question: "How many P1 incidents were resolved last quarter?",
  top_k: 5,
  search_mode: "auto",
  enable_rerank: true,
  enable_hyde: false,
  enable_crag: true,
  enable_self_reflective: false,
};

const hybridPayload = {
  question:
    "How many P1 incidents were resolved last quarter and what does our escalation policy say for P1 incidents?",
  top_k: 5,
  search_mode: "auto",
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

export function runRag(data) {
  const res = postQuery(data.url, data.token, ragPayload, {
    scenario: "mixed_rag",
  });
  requireStatus(res, 200, "mixed rag query returned 200");
  const body = jsonBody(res);
  check(body, {
    "mixed rag answer present": (b) => Boolean(b?.answer),
  });
  sleep(1);
}

export function runSql(data) {
  const result = completeSqlFlow(data.url, data.token, sqlPayload, {
    scenario: "mixed_sql",
  });
  const finalJson = result.executeJson || result.queryJson;
  check(finalJson, {
    "mixed sql final present": (b) => Boolean(b?.answer || b?.pending_sql),
  });
  sleep(1);
}

export function runHybrid(data) {
  const result = completeSqlFlow(data.url, data.token, hybridPayload, {
    scenario: "mixed_hybrid",
  });
  const finalJson = result.executeJson || result.queryJson;
  check(finalJson, {
    "mixed hybrid answer present": (b) => Boolean(b?.answer || b?.pending_sql),
  });
  sleep(1);
}
