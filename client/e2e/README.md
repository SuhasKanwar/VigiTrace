# End-to-end suite

Headless-Chrome tests that drive the real stack — Next.js client, Express API,
FastAPI service and a mock recorder — rather than mocking the boundaries. The
point is to prove the wiring, so these tests fail when the layers disagree,
which is exactly the class of bug unit tests miss.

## Prerequisites

All four processes must be running before the suite starts. `assertStackIsUp()`
refuses to run against a half-started stack, because a confusing failure is
worse than none.

| Service | Port | Start from | Command |
| --- | --- | --- | --- |
| FastAPI service | 8000 | `service/` | `.venv/bin/python app.py` |
| Express API | 9000 | `server/` | `npm run build && npm run start` |
| Next.js client | 3000 | `client/` | `npm run build && npm run start` |
| Mock recorder | 8081 | `service/` | `.venv/bin/python -m tests.mock_dvr --vendor hikvision --port 8081 --username admin --password Admin12345` |

The mock recorder is the same Hikvision ISAPI server the service's 364 unit
tests run against (`service/tests/mock_dvr/`), served on a fixed port instead of
an ephemeral one. Using one mock for both suites means the browser tests and the
adapter tests are talking to identical protocol behaviour rather than to two
imitations that drift apart. It implements real RFC 2617 digest auth, so wrong
credentials genuinely fail.

Its fixtures: model `DS-7208HQHI-K1`, six channels (`Front Gate`, `Reception`,
`Corridor`, `Store Room`, and two IP cameras on channels 33/34), one ~1.8 TB
volume, and a clock offset from the host so drift assertions have something to
measure. `--vendor dahua` serves the Dahua CGI surface instead.

Chrome is located automatically; set `CHROME_PATH` to override. The suite uses
`puppeteer-core` against the system browser deliberately — no 300 MB browser
download is added to the repository.

## Running

```bash
npm run e2e                                   # every spec
npm run e2e:one -- e2e/specs/auth.spec.mjs    # one file
```

Override endpoints with `CLIENT_URL`, `SERVER_URL`, `SERVICE_URL`,
`MOCK_DVR_PORT`, `MOCK_DVR_USER`, `MOCK_DVR_PASS`, and the per-step wait budget
with `E2E_TIMEOUT` (default 45s — device actions hit a real recorder).

## Writing specs

Use `harness.mjs` rather than driving Puppeteer directly:

- **`goto(page, path, { waitFor, expectPath })`** — never `waitUntil:
  "networkidle2"` on a dashboard route. Next.js prefetches sidebar links, so the
  network never goes idle and the navigation times out.
- **`gotoExpectingRedirect(page, path, destination)`** — for routes that bounce.
  `redirect()` in the App Router does not answer with an HTTP 30x; it returns 200
  carrying an RSC payload and navigates client-side after hydration, so waiting
  on a selector races the swap.
- **`newPage(browser)`** records `page.collected.{consoleErrors, pageErrors,
  failedRequests}`; **`assertNoPageErrors(page)`** fails the test on any of them.
  A page that renders correctly while throwing in the console is not passing.
- **`uniqueEmail()`** for every account, so specs never collide or depend on
  each other's leftovers.

Two traps worth knowing, both of which have already produced false results here:

- `"IDENTIFIED"` is a substring of `"UNIDENTIFIED"`, which the device page
  renders *before* identification. Waiting on that text returns immediately.
  Wait for something unambiguous instead, such as the channel table filling.
- Session cookies leak between tests that share a browser context. Give each
  test its own `browser.createBrowserContext()` when it asserts signed-out
  behaviour.
