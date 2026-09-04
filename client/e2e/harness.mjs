/**
 * Shared browser harness for the VigiTrace end-to-end suite.
 *
 * Uses puppeteer-core against the system Chrome rather than a bundled browser,
 * so the suite adds no 300MB download to the repo. Set CHROME_PATH to override.
 *
 * The suite drives the real stack - Next.js client, Express API, FastAPI
 * service and a mock recorder - because the point is to prove the wiring, not
 * to re-test components against fixtures.
 */

import assert from "node:assert/strict";
import puppeteer from "puppeteer-core";

export const CLIENT_URL = process.env.CLIENT_URL ?? "http://localhost:3000";
export const SERVER_URL = process.env.SERVER_URL ?? "http://localhost:9000";
export const SERVICE_URL = process.env.SERVICE_URL ?? "http://localhost:8000";
export const MOCK_DVR_PORT = Number(process.env.MOCK_DVR_PORT ?? 8081);
export const MOCK_DVR_USER = process.env.MOCK_DVR_USER ?? "admin";
export const MOCK_DVR_PASS = process.env.MOCK_DVR_PASS ?? "Admin12345";

const CHROME_CANDIDATES = [
    process.env.CHROME_PATH,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
].filter(Boolean);

export const DEFAULT_TIMEOUT = Number(process.env.E2E_TIMEOUT ?? 45000);

async function resolveChrome() {
    const { existsSync } = await import("node:fs");
    const found = CHROME_CANDIDATES.find((p) => existsSync(p));
    if (!found) {
        throw new Error(
            `No Chrome binary found. Set CHROME_PATH. Tried:\n  ${CHROME_CANDIDATES.join("\n  ")}`,
        );
    }
    return found;
}

export async function launchBrowser() {
    return puppeteer.launch({
        executablePath: await resolveChrome(),
        headless: "new",
        args: ["--no-sandbox", "--disable-dev-shm-usage", "--window-size=1440,900"],
        defaultViewport: { width: 1440, height: 900 },
    });
}

/**
 * A page that records its own console errors and failed requests.
 *
 * A page that renders correctly while throwing in the console is not passing,
 * so every spec can assert on `page.collected` at the end.
 */
export async function newPage(browser) {
    const page = await browser.newPage();
    page.setDefaultTimeout(DEFAULT_TIMEOUT);
    page.setDefaultNavigationTimeout(DEFAULT_TIMEOUT);
    const collected = { consoleErrors: [], pageErrors: [], failedRequests: [] };
    page.collected = collected;
    page.on("console", (msg) => {
        if (msg.type() === "error") collected.consoleErrors.push(msg.text().slice(0, 300));
    });
    page.on("pageerror", (err) => collected.pageErrors.push(String(err.message).slice(0, 300)));
    page.on("response", (res) => {
        const url = res.url();
        // NextAuth answers 401 by design while probing for a session, and
        // Next.js prefetches sidebar links whose routes may not exist yet.
        const expected =
            url.includes("/api/auth/session") ||
            (res.status() === 404 && /\/dashboard\/(cases|acquisition|analysis|reports|settings)/.test(url));
        if (res.status() >= 400 && !expected) {
            collected.failedRequests.push(`${res.status()} ${url}`);
        }
    });
    return page;
}


/**
 * Navigate and wait for the app to be interactive.
 *
 * Deliberately NOT `networkidle2`: the dashboard sidebar renders several
 * <Link>s and Next.js prefetches each one, so the network never goes idle and
 * every navigation would time out. Waiting for the DOM plus the app's own
 * readiness signal is both faster and stable.
 */
export async function goto(page, path, { waitFor, expectPath } = {}) {
    const url = path.startsWith("http") ? path : `${CLIENT_URL}${path}`;
    await page.goto(url, { waitUntil: "domcontentloaded" });

    // These routes do not answer with an HTTP 30x. `redirect()` in the App
    // Router returns 200 carrying an RSC payload (NEXT_REDIRECT;replace;...),
    // and the navigation happens client-side after hydration. Waiting on a
    // selector races that swap and can throw "Node with given id does not
    // belong to the document", so settle on the URL first.
    if (expectPath) {
        await page.waitForFunction(
            (want) => location.pathname.startsWith(want),
            { timeout: DEFAULT_TIMEOUT },
            expectPath,
        );
    }

    await page.waitForFunction(() => document.readyState !== "loading", { timeout: DEFAULT_TIMEOUT });
    if (waitFor) await page.waitForSelector(waitFor, { timeout: DEFAULT_TIMEOUT });
    return page;
}

/**
 * Navigate to a route that is expected to bounce elsewhere, and wait for the
 * destination. Use this rather than `goto()` whenever the redirect itself is
 * the thing under test.
 */
export async function gotoExpectingRedirect(page, path, destination) {
    return goto(page, path, { expectPath: destination });
}

export function uniqueEmail(prefix = "e2e") {
    return `${prefix}.${Date.now()}.${Math.random().toString(36).slice(2, 8)}@example.com`;
}

export const PASSWORD = "Passw0rd!23";

/** Register through the real UI, then wait for the dashboard to take over. */
export async function signUpViaUi(page, { name = "E2E Tester", email = uniqueEmail(), password = PASSWORD } = {}) {
    await page.goto(`${CLIENT_URL}/auth/signup`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('input[name="name"], input[name="email"]');
    const hasName = await page.$('input[name="name"]');
    if (hasName) await page.type('input[name="name"]', name);
    await page.type('input[name="email"]', email);
    await page.type('input[name="password"]', password);
    await Promise.all([
        page.waitForFunction(() => location.pathname.startsWith("/dashboard"), { timeout: DEFAULT_TIMEOUT }),
        page.click('button[type="submit"]'),
    ]);
    return { name, email, password };
}

export async function signInViaUi(page, { email, password = PASSWORD }) {
    await page.goto(`${CLIENT_URL}/auth/signin`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('input[name="email"]');
    await page.type('input[name="email"]', email);
    await page.type('input[name="password"]', password);
    await Promise.all([
        page.waitForFunction(() => location.pathname.startsWith("/dashboard"), { timeout: DEFAULT_TIMEOUT }),
        page.click('button[type="submit"]'),
    ]);
}

/** Register straight against the API, for specs whose subject is not signup. */
export async function apiSignUp({ name = "API Tester", email = uniqueEmail(), password = PASSWORD } = {}) {
    const res = await fetch(`${SERVER_URL}/api/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, password }),
    });
    const body = await res.json();
    assert.equal(body.success, true, `signup failed: ${body.message}`);
    return { name, email, password, token: body.data.token };
}

export async function apiCreateDevice(token, overrides = {}) {
    const res = await fetch(`${SERVER_URL}/api/devices`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
            name: "Seeded NVR",
            host: "127.0.0.1",
            httpPort: MOCK_DVR_PORT,
            useHttps: false,
            username: MOCK_DVR_USER,
            password: MOCK_DVR_PASS,
            ...overrides,
        }),
    });
    const body = await res.json();
    assert.equal(body.success, true, `device create failed: ${body.message}`);
    return body.data.device;
}

export async function apiPost(token, path, payload = {}) {
    const res = await fetch(`${SERVER_URL}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(payload),
    });
    return res.json();
}

/** Visible text of the whole page, whitespace-collapsed for robust matching. */
export async function pageText(page) {
    return (await page.evaluate(() => document.body.innerText)).replace(/\s+/g, " ");
}

export async function textOf(page, selector) {
    return page.$eval(selector, (el) => el.textContent.trim()).catch(() => null);
}

/** Click whichever visible element carries this exact label. */
export async function clickByText(page, text, selector = "button, a") {
    const handle = await page.evaluateHandle(
        (sel, label) =>
            [...document.querySelectorAll(sel)].find(
                (el) => el.textContent.trim().toLowerCase() === label.toLowerCase(),
            ) ?? null,
        selector,
        text,
    );
    const element = handle.asElement();
    assert.ok(element, `No ${selector} found with text "${text}"`);
    await element.click();
    return element;
}

export async function waitForText(page, text, timeout = DEFAULT_TIMEOUT) {
    await page.waitForFunction(
        (needle) => document.body.innerText.replace(/\s+/g, " ").includes(needle),
        { timeout },
        text,
    );
}

/** Fail a spec if the page logged errors while it ran. */
export function assertNoPageErrors(page, { allowConsole = [] } = {}) {
    const { pageErrors, consoleErrors, failedRequests } = page.collected;
    assert.deepEqual(pageErrors, [], `Uncaught page errors:\n${pageErrors.join("\n")}`);
    const unexpected = consoleErrors.filter((e) => !allowConsole.some((ok) => e.includes(ok)));
    assert.deepEqual(unexpected, [], `Console errors:\n${unexpected.join("\n")}`);
    assert.deepEqual(failedRequests, [], `Failed requests:\n${failedRequests.join("\n")}`);
}

/** Refuse to run against a half-started stack; a confusing failure is worse than none. */
export async function assertStackIsUp() {
    const checks = [
        [`${CLIENT_URL}/`, "Next.js client"],
        [`${SERVER_URL}/health`, "Express API"],
        [`${SERVICE_URL}/health`, "FastAPI service"],
        [`http://127.0.0.1:${MOCK_DVR_PORT}/`, "mock recorder"],
    ];
    for (const [url, label] of checks) {
        try {
            const res = await fetch(url, { signal: AbortSignal.timeout(5000) });
            // The mock recorder answers 401 unauthenticated, which still proves it is listening.
            assert.ok(res.status < 500, `${label} at ${url} returned ${res.status}`);
        } catch (error) {
            throw new Error(`${label} is not reachable at ${url}: ${error.message}`);
        }
    }
}
