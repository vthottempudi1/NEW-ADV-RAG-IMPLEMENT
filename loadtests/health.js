import http from "k6/http";
import { check, sleep } from "k6";
import { baseUrl } from "./lib.js";

export const options = {
  vus: Number(__ENV.VUS || 5),
  duration: __ENV.DURATION || "1m",
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<1000"],
  },
};

export default function () {
  const res = http.get(`${baseUrl()}/health`, {
    tags: { endpoint: "health" },
  });

  check(res, {
    "health status 200": (r) => r.status === 200,
    "health body has ok": (r) => String(r.body).includes('"status":"ok"'),
  });

  sleep(1);
}
