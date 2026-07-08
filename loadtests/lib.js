import http from "k6/http";
import { check, fail } from "k6";

export function baseUrl() {
  return (__ENV.BASE_URL || "https://api.aiscientificlabs.com").replace(/\/+$/, "");
}

export function authCredentials() {
  const username = __ENV.LOADTEST_USERNAME || __ENV.USERNAME;
  const password = __ENV.LOADTEST_PASSWORD || __ENV.PASSWORD;
  if (!username || !password) {
    fail("Set LOADTEST_USERNAME and LOADTEST_PASSWORD environment variables.");
  }
  return { username, password };
}

export function login(url) {
  const credentials = authCredentials();
  const res = http.post(
    `${url}/auth/login`,
    JSON.stringify(credentials),
    {
      headers: { "Content-Type": "application/json" },
      tags: { endpoint: "auth_login" },
    },
  );

  const ok = check(res, {
    "login returned 200": (r) => r.status === 200,
    "login returned token": (r) => {
      try {
        return Boolean(r.json("token"));
      } catch {
        return false;
      }
    },
  });

  if (!ok) {
    fail(`Login failed. status=${res.status} body=${truncate(res.body)}`);
  }

  return { token: res.json("token") };
}

export function authHeaders(token) {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

export function postQuery(url, token, payload, tags = {}) {
  return http.post(
    `${url}/query`,
    JSON.stringify(payload),
    {
      headers: authHeaders(token),
      tags: { endpoint: "query", ...tags },
    },
  );
}

export function approveSql(url, token, queryId, approved = true, tags = {}) {
  return http.post(
    `${url}/query/sql/execute`,
    JSON.stringify({ query_id: queryId, approved }),
    {
      headers: authHeaders(token),
      tags: { endpoint: "sql_execute", ...tags },
    },
  );
}

export function jsonBody(res) {
  try {
    return res.json();
  } catch {
    return null;
  }
}

export function truncate(value, max = 220) {
  if (!value) {
    return "";
  }
  const text = String(value).replace(/\s+/g, " ").trim();
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

export function requireStatus(res, expected, label) {
  const ok = check(res, {
    [label]: (r) => r.status === expected,
  });
  if (!ok) {
    fail(`${label} failed. status=${res.status} body=${truncate(res.body)}`);
  }
}

export function completeSqlFlow(url, token, payload, tags = {}) {
  const queryRes = postQuery(url, token, payload, tags);
  requireStatus(queryRes, 200, "query returned 200");

  const queryJson = jsonBody(queryRes);
  if (!queryJson) {
    fail(`Query did not return JSON. body=${truncate(queryRes.body)}`);
  }

  if (!queryJson.pending_sql) {
    return {
      queryRes,
      queryJson,
      executeRes: null,
      executeJson: null,
      approved: false,
    };
  }

  const executeRes = approveSql(url, token, queryJson.pending_sql.query_id, true, tags);
  requireStatus(executeRes, 200, "sql approval returned 200");

  const executeJson = jsonBody(executeRes);
  if (!executeJson) {
    fail(`SQL execute did not return JSON. body=${truncate(executeRes.body)}`);
  }

  return {
    queryRes,
    queryJson,
    executeRes,
    executeJson,
    approved: true,
  };
}
