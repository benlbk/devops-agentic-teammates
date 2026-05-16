import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'https://devops.13.215.130.82.nip.io';

// Custom metrics
const errorRate = new Rate('errors');
const orchestratorLatency = new Trend('orchestrator_latency', true);
const frontendLatency = new Trend('frontend_latency', true);
const backendLatency = new Trend('backend_latency', true);

export const options = {
  insecureSkipTLSVerify: true,
  scenarios: {
    // Ramp up to test HPA scaling
    smoke: {
      executor: 'constant-vus',
      vus: 5,
      duration: '30s',
      startTime: '0s',
      tags: { phase: 'smoke' },
    },
    load: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '1m', target: 20 },
        { duration: '2m', target: 20 },
        { duration: '1m', target: 50 },
        { duration: '2m', target: 50 },
        { duration: '1m', target: 0 },
      ],
      startTime: '30s',
      tags: { phase: 'load' },
    },
    spike: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '10s', target: 100 },
        { duration: '30s', target: 100 },
        { duration: '10s', target: 0 },
      ],
      startTime: '8m',
      tags: { phase: 'spike' },
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<2000', 'p(99)<5000'],
    errors: ['rate<0.1'],
    orchestrator_latency: ['p(95)<1000'],
    frontend_latency: ['p(95)<1500'],
    backend_latency: ['p(95)<2000'],
  },
};

export default function () {
  // Test orchestrator health
  const orchRes = http.get(`${BASE_URL}/orchestrator/health`);
  orchestratorLatency.add(orchRes.timings.duration);
  check(orchRes, { 'orchestrator healthy': (r) => r.status === 200 }) || errorRate.add(1);

  // Test frontend
  const feRes = http.get(`${BASE_URL}/dashboard/`);
  frontendLatency.add(feRes.timings.duration);
  check(feRes, { 'frontend ok': (r) => r.status === 200 || r.status === 302 }) || errorRate.add(1);

  // Test backend via frontend API (if exists)
  const beRes = http.get(`${BASE_URL}/app/`);
  backendLatency.add(beRes.timings.duration);
  check(beRes, { 'backend ok': (r) => r.status === 200 || r.status === 302 }) || errorRate.add(1);

  // Test orchestrator API endpoints
  const infoRes = http.get(`${BASE_URL}/orchestrator/info`);
  check(infoRes, { 'orchestrator info': (r) => r.status === 200 });

  const metricsRes = http.get(`${BASE_URL}/orchestrator/api/metrics/dora`);
  check(metricsRes, { 'dora metrics': (r) => r.status === 200 });

  sleep(0.5);
}
