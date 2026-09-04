/**
 * End-to-end coverage for the devices list (/dashboard/devices) and the
 * registration form (/dashboard/devices/new).
 *
 * Every test signs up its own investigator via a fresh uniqueEmail() so runs
 * never collide with each other or with other spec files hitting the same
 * running server/DB.
 */

import test, { before, after, describe } from "node:test";
import assert from "node:assert/strict";
import {
    CLIENT_URL,
    SERVER_URL,
    MOCK_DVR_PORT,
    MOCK_DVR_USER,
    MOCK_DVR_PASS,
    launchBrowser,
    newPage,
    goto,
    apiSignUp,
    apiCreateDevice,
    signUpViaUi,
    signInViaUi,
    pageText,
    textOf,
    clickByText,
    waitForText,
    assertNoPageErrors,
    assertStackIsUp,
} from "../harness.mjs";

const FORM_URL = `${CLIENT_URL}/dashboard/devices/new`;
const LIST_URL = `${CLIENT_URL}/dashboard/devices`;

/**
 * A fresh incognito-style browser context per test.
 *
 * Puppeteer's `browser.newPage()` opens pages that share ONE cookie jar for
 * the whole browser instance. With one `browser` shared across every test in
 * this file, a NextAuth session cookie set by test N's signUpViaUi/signInViaUi
 * would still be attached on test N+1's very first request - and /auth/signup
 * and /auth/signin both server-redirect an already-authenticated visitor
 * straight to /dashboard (see their page.tsx: `if (await getAuthSession())
 * redirect("/dashboard")`), before the form ever renders. That leaves
 * `waitForSelector('input[name="email"]')` waiting on a page that will never
 * have that input, hanging for the full 45s timeout. An isolated
 * BrowserContext per test gives each test its own cookie jar, exactly like a
 * new incognito window, so investigator sessions never bleed across tests.
 */
async function newIsolatedPage(browser) {
    const context = await browser.createBrowserContext();
    const page = await newPage(context);
    return { page, context };
}

/**
 * Set a React-controlled text field's value and let React see it.
 *
 * Two approaches were tried and rejected first:
 *  - `{ clickCount: 3 }` triple-click-to-select-all, then Backspace, then
 *    page.type(): flaky under Puppeteer's simulated clicks - three rapid
 *    clicks sometimes land as unrelated single clicks instead of one
 *    detail=3 event, leaving the cursor at position 0 with nothing selected.
 *  - Home, then Shift+End, then Backspace: reliable in isolation, but
 *    demonstrably flaky (confirmed by reading `selectionStart`/`selectionEnd`
 *    back) once it was the Nth field touched in a sequence - Shift+End
 *    sometimes failed to extend the selection, so Backspace deleted nothing
 *    and the typed value got prepended instead of replacing "80"
 *    (e.g. typing "0" over the pre-filled httpPort left "080", not "0").
 *
 * Calling the native <input> value setter directly and dispatching a real
 * "input" event is what Testing Library's fireEvent does for exactly this
 * reason, and is reliable regardless of ordering: React attaches its change
 * listener via native "input" event delegation, so this is indistinguishable
 * to the app from a user's keystroke reaching the same handler - unlike
 * `el.value = ...` alone, which React's own value tracking would otherwise
 * silently revert on the next render.
 */
async function setValue(page, selector, value) {
    await page.$eval(
        selector,
        (el, val) => {
            const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value").set;
            setter.call(el, val);
            el.dispatchEvent(new Event("input", { bubbles: true }));
        },
        value,
    );
}

async function fillDeviceForm(page, { name, host, httpPort, username, password } = {}) {
    if (name !== undefined) await setValue(page, "#device-name", name);
    if (host !== undefined) await setValue(page, "#device-host", host);
    if (httpPort !== undefined) await setValue(page, "#device-httpPort", httpPort);
    if (username !== undefined) await setValue(page, "#device-username", username);
    if (password !== undefined) await setValue(page, "#device-password", password);
}

async function submitDeviceForm(page) {
    await clickByText(page, "Register device");
}

function fieldError(page, field) {
    return textOf(page, `#device-${field}-error`);
}

/** Whichever table row's text contains this device name, whitespace-collapsed. */
async function deviceRowText(page, deviceName) {
    return page.evaluate((name) => {
        const row = [...document.querySelectorAll("table tbody tr")].find((tr) => tr.innerText.includes(name));
        return row ? row.innerText.replace(/\s+/g, " ").trim() : null;
    }, deviceName);
}

/**
 * Every input/select in the form must resolve to a label through one of the
 * three legitimate mechanisms (explicit for/id, nesting, or an aria-label).
 * A screen-reader user filling in a forensic tool with an unlabelled field
 * is exactly the kind of accessibility bug that is easy to introduce and
 * easy to miss in a purely visual review.
 */
async function unlabelledFormControls(page) {
    return page.$$eval("form input, form select", (elements) =>
        elements
            .filter((el) => el.type !== "hidden")
            .filter((el) => {
                const hasAriaLabel = el.getAttribute("aria-label")?.trim();
                const hasAriaLabelledBy = el.getAttribute("aria-labelledby")?.trim();
                const hasForLabel = el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                const nestedInLabel = el.closest("label");
                return !(hasAriaLabel || hasAriaLabelledBy || hasForLabel || nestedInLabel);
            })
            .map((el) => el.name || el.id || el.outerHTML.slice(0, 120)),
    );
}

/** Collects response bodies only from the endpoints that could ever legitimately carry a stored secret. */
function watchApiResponseBodies(page) {
    const bodies = [];
    page.on("response", async (res) => {
        const url = res.url();
        if (!url.startsWith(SERVER_URL) && !url.includes("/api/auth")) return;
        try {
            bodies.push({ url, text: await res.text() });
        } catch {
            // Redirects and already-consumed bodies carry nothing to check.
        }
    });
    return bodies;
}

describe("devices list and registration form", () => {
    let browser;

    before(async () => {
        await assertStackIsUp();
        browser = await launchBrowser();
    });
    after(async () => browser?.close());

    test("a brand-new user sees a clear empty state with a CTA into the registration form", async () => {
        const { page, context } = await newIsolatedPage(browser);
        try {
            await signUpViaUi(page);
            await goto(page, "/dashboard/devices");

            // Regression guard: a spinner that never resolves would hang here
            // rather than fail cleanly, so wait on the actual terminal text.
            await waitForText(page, "No devices on record");

            const spinner = await page.$('[role="status"][aria-busy="true"]');
            assert.equal(spinner, null, "the loading skeleton is still showing after the empty state resolved");

            const ctas = await page.$$eval('a[href="/dashboard/devices/new"]', (links) =>
                links.map((l) => l.textContent.trim()),
            );
            assert.ok(ctas.length > 0, "no link to /dashboard/devices/new was found on the empty devices page");
            assert.ok(ctas.some((t) => /add device/i.test(t)), `CTA link text was unexpected: ${ctas.join(", ")}`);

            assertNoPageErrors(page);
        } finally {
            await context.close();
        }
    });

    test("the registration form exposes name, host, port, https, username, password and vendor hint, each with a real label", async () => {
        const { page, context } = await newIsolatedPage(browser);
        try {
            await signUpViaUi(page);
            await goto(page, "/dashboard/devices/new", { waitFor: "#device-name" });

            const unlabelled = await unlabelledFormControls(page);
            assert.deepEqual(unlabelled, [], `unlabelled form control(s): ${unlabelled.join(", ")}`);

            // Field presence plus the label text a reader would actually see,
            // not just "a label element exists somewhere".
            assert.match(await textOf(page, 'label[for="device-name"]'), /device name/i);
            assert.match(await textOf(page, 'label[for="device-host"]'), /^host$/i);
            assert.match(await textOf(page, 'label[for="device-httpPort"]'), /http port/i);
            assert.match(await textOf(page, 'label[for="device-username"]'), /username/i);
            assert.match(await textOf(page, 'label[for="device-password"]'), /password/i);
            assert.match(await textOf(page, 'label[for="device-vendorHint"]'), /vendor/i);

            const passwordType = await page.$eval("#device-password", (el) => el.type);
            assert.equal(passwordType, "password", "the password field is not masked (type != password)");

            const httpsCheckbox = await page.$('input[name="useHttps"][type="checkbox"]');
            assert.ok(httpsCheckbox, "no HTTPS toggle checkbox found");
            const httpsLabelText = await page.$eval('input[name="useHttps"]', (el) => el.closest("label")?.textContent ?? "");
            assert.match(httpsLabelText, /use https/i);

            const vendorOptions = await page.$$eval("#device-vendorHint option", (opts) => opts.map((o) => o.value));
            assert.ok(vendorOptions.includes(""), "vendor hint has no auto-detect option");

            assertNoPageErrors(page);
        } finally {
            await context.close();
        }
    });

    test("submitting the empty form shows inline errors for every required field and does not navigate", async () => {
        const { page, context } = await newIsolatedPage(browser);
        try {
            await signUpViaUi(page);
            await goto(page, "/dashboard/devices/new", { waitFor: "#device-name" });

            await submitDeviceForm(page);
            await page.waitForSelector("#device-name-error");

            assert.equal(page.url(), FORM_URL, "the form navigated away despite failing validation");
            assert.match(await fieldError(page, "name"), /name that will identify/i);
            assert.match(await fieldError(page, "host"), /ip address or hostname/i);
            assert.match(await fieldError(page, "username"), /credentials are required/i);
            assert.match(await fieldError(page, "password"), /enter the password/i);
            // httpPort defaults to a valid "80", so an empty submission must
            // NOT also flag the port - a stray port error here would mean
            // the default value regressed to something invalid.
            assert.equal(await fieldError(page, "httpPort"), null, "the pre-filled default port 80 was unexpectedly flagged as invalid");

            // The first invalid field (name, per validate()'s field order) should also receive focus.
            const focusedId = await page.evaluate(() => document.activeElement?.id);
            assert.equal(focusedId, "device-name");

            assertNoPageErrors(page);
        } finally {
            await context.close();
        }
    });

    test("a blank host with everything else valid is rejected and does not navigate", async () => {
        const { page, context } = await newIsolatedPage(browser);
        try {
            await signUpViaUi(page);
            await goto(page, "/dashboard/devices/new", { waitFor: "#device-name" });

            await fillDeviceForm(page, { name: "Blank Host Test", username: "admin", password: "s3cret-pass" });
            // host is deliberately left blank.
            await submitDeviceForm(page);
            await page.waitForSelector("#device-host-error");

            assert.equal(page.url(), FORM_URL);
            assert.match(await fieldError(page, "host"), /ip address or hostname/i);
            // Confirms the host validator doesn't spuriously flag its neighbours.
            assert.equal(await fieldError(page, "name"), null);
            assert.equal(await fieldError(page, "username"), null);
            assert.equal(await fieldError(page, "password"), null);

            assertNoPageErrors(page);
        } finally {
            await context.close();
        }
    });

    test("out-of-range ports (0, 70000, non-numeric) are all rejected and never navigate", async () => {
        const { page, context } = await newIsolatedPage(browser);
        try {
            await signUpViaUi(page);
            await goto(page, "/dashboard/devices/new", { waitFor: "#device-name" });

            await fillDeviceForm(page, { name: "Port Test", host: "192.0.2.10", username: "admin", password: "s3cret-pass" });

            for (const badPort of ["0", "70000", "notanumber"]) {
                await setValue(page, "#device-httpPort", badPort);
                await submitDeviceForm(page);
                await page.waitForSelector("#device-httpPort-error");
                assert.equal(page.url(), FORM_URL, `port "${badPort}" navigated away despite being invalid`);
                assert.match(
                    await fieldError(page, "httpPort"),
                    /whole number between 1 and 65535/i,
                    `port "${badPort}" did not produce the expected range error`,
                );
            }

            // A valid port must clear the error - proves this is live validation, not a stuck message.
            await setValue(page, "#device-httpPort", "554");
            const cleared = await page.$("#device-httpPort-error");
            assert.equal(cleared, null, "the port error did not clear once a valid port was entered");

            assertNoPageErrors(page);
        } finally {
            await context.close();
        }
    });

    test("registering a device against the mock recorder navigates to the device and shows its name and endpoint", async () => {
        const { page, context } = await newIsolatedPage(browser);
        try {
            await signUpViaUi(page);
            await goto(page, "/dashboard/devices/new", { waitFor: "#device-name" });

            const deviceName = `Happy Path Recorder ${Date.now()}`;
            await fillDeviceForm(page, {
                name: deviceName,
                host: "127.0.0.1",
                httpPort: String(MOCK_DVR_PORT),
                username: MOCK_DVR_USER,
                password: MOCK_DVR_PASS,
            });

            await Promise.all([
                page.waitForFunction(() => location.pathname !== "/dashboard/devices/new"),
                submitDeviceForm(page),
            ]);

            assert.match(
                page.url(),
                new RegExp(`^${CLIENT_URL}/dashboard/devices(/.+)?$`),
                `expected navigation to the device or list, got ${page.url()}`,
            );

            await waitForText(page, deviceName);
            const text = await pageText(page);
            assert.ok(
                text.includes(`127.0.0.1:${MOCK_DVR_PORT}`),
                `expected the new device's host:port to appear on the page, got: ${text.slice(0, 400)}`,
            );

            assertNoPageErrors(page);
        } finally {
            await context.close();
        }
    });

    test("the list renders name, host:port, vendor badge, state badge and last-probed for every seeded device", async () => {
        const { email, password, token } = await apiSignUp();
        const seeded = [
            await apiCreateDevice(token, { name: "Front Gate NVR", host: "127.0.0.1", httpPort: MOCK_DVR_PORT, username: MOCK_DVR_USER, password: MOCK_DVR_PASS }),
            await apiCreateDevice(token, { name: "Warehouse DVR", host: "198.51.100.20", httpPort: 8082, username: "admin", password: "whatever-2" }),
            await apiCreateDevice(token, { name: "Back Lot Camera Hub", host: "198.51.100.21", httpPort: 8083, username: "admin", password: "whatever-3" }),
        ];

        const { page, context } = await newIsolatedPage(browser);
        try {
            await signInViaUi(page, { email, password });
            await goto(page, "/dashboard/devices");
            await waitForText(page, seeded[0].name);

            const summary = await pageText(page);
            assert.ok(summary.includes(`${seeded.length} recorders`), `expected the registry panel to report ${seeded.length} recorders`);

            for (const device of seeded) {
                const row = await deviceRowText(page, device.name);
                assert.ok(row, `no table row found for device "${device.name}"`);
                assert.ok(row.includes(`${device.host}:${device.httpPort}`), `row for "${device.name}" is missing its host:port: ${row}`);
                // None of these devices has been probed, so vendor is UNKNOWN and state is the default REGISTERED.
                // The badge must read as human text, not the raw enum or a leaked undefined/null.
                assert.ok(/unidentified/i.test(row), `row for "${device.name}" did not show an UNIDENTIFIED vendor badge: ${row}`);
                assert.ok(/\bREGISTERED\b/.test(row), `row for "${device.name}" did not show a REGISTERED state badge: ${row}`);
                assert.ok(/never probed/i.test(row), `row for "${device.name}" did not show the "never probed" placeholder: ${row}`);
                assert.ok(!/\bundefined\b/i.test(row) && !/\bnull\b/i.test(row), `row for "${device.name}" leaked undefined/null into the DOM: ${row}`);
            }

            assertNoPageErrors(page);
        } finally {
            await context.close();
        }
    });

    test("the device password never appears in the rendered DOM or in any API response body the page received", async () => {
        const distinctivePassword = `Cr3d-Guard-${Date.now()}-Secret!`;
        const { email, password, token } = await apiSignUp();
        const device = await apiCreateDevice(token, {
            name: "Credential Guard NVR",
            host: "203.0.113.5",
            httpPort: 8090,
            username: "admin",
            password: distinctivePassword,
        });

        const { page, context } = await newIsolatedPage(browser);
        try {
            const bodies = watchApiResponseBodies(page);

            await signInViaUi(page, { email, password });
            assert.ok(!(await page.content()).includes(distinctivePassword), "password leaked into the dashboard DOM right after sign-in");

            await goto(page, "/dashboard/devices");
            await waitForText(page, device.name);
            assert.ok(!(await page.content()).includes(distinctivePassword), "password leaked into the devices list DOM");

            await goto(page, `/dashboard/devices/${device.id}`);
            await waitForText(page, device.name);
            assert.ok(!(await page.content()).includes(distinctivePassword), "password leaked into the device detail DOM");

            const leaking = bodies.filter((b) => b.text.includes(distinctivePassword));
            assert.deepEqual(
                leaking.map((b) => b.url),
                [],
                "password leaked into an API response body the page received",
            );

            assertNoPageErrors(page);
        } finally {
            await context.close();
        }
    });

    test('the sidebar "Devices" link navigates correctly and is marked aria-current="page" on both the list and a nested route', async () => {
        const { page, context } = await newIsolatedPage(browser);
        try {
            await signUpViaUi(page);

            const devicesLinkHref = await page.$eval(
                'nav[aria-label="Dashboard navigation"] a[href="/dashboard/devices"]',
                (el) => el.getAttribute("href"),
            );
            assert.equal(devicesLinkHref, "/dashboard/devices");

            await Promise.all([
                page.waitForFunction(() => location.pathname === "/dashboard/devices"),
                clickByText(page, "Devices", 'nav[aria-label="Dashboard navigation"] a'),
            ]);
            assert.equal(page.url(), LIST_URL);

            let ariaCurrent = await page.$eval(
                'nav[aria-label="Dashboard navigation"] a[href="/dashboard/devices"]',
                (el) => el.getAttribute("aria-current"),
            );
            assert.equal(ariaCurrent, "page", "the Devices link is not marked current while on /dashboard/devices");

            const overviewCurrent = await page.$eval(
                'nav[aria-label="Dashboard navigation"] a[href="/dashboard"]',
                (el) => el.getAttribute("aria-current"),
            );
            assert.notEqual(overviewCurrent, "page", "Overview was also marked current while on /dashboard/devices");

            // Nested-route highlighting: this logic was recently changed and is the specific thing to verify.
            await goto(page, "/dashboard/devices/new", { waitFor: "#device-name" });
            ariaCurrent = await page.$eval(
                'nav[aria-label="Dashboard navigation"] a[href="/dashboard/devices"]',
                (el) => el.getAttribute("aria-current"),
            );
            assert.equal(ariaCurrent, "page", "the Devices link lost aria-current on the nested /dashboard/devices/new route");

            assertNoPageErrors(page);
        } finally {
            await context.close();
        }
    });

    test("deleting a device through its detail page removes it from the list", async () => {
        const { email, password, token } = await apiSignUp();
        const device = await apiCreateDevice(token, {
            name: "Deletable NVR",
            host: "203.0.113.9",
            httpPort: 9099,
            username: "admin",
            password: "whatever-9",
        });

        const { page, context } = await newIsolatedPage(browser);
        try {
            await signInViaUi(page, { email, password });
            await goto(page, `/dashboard/devices/${device.id}`);
            await waitForText(page, device.name);

            await clickByText(page, "Remove device");
            await waitForText(page, "Confirm removal");

            await Promise.all([
                page.waitForFunction(() => location.pathname === "/dashboard/devices"),
                clickByText(page, "Confirm removal"),
            ]);
            assert.equal(page.url(), LIST_URL);

            // This was the user's only device, so deleting it should also
            // roll the list back to the empty state, not just drop one row.
            // Note: the success toast's own text ("Device <name> ... deleted")
            // legitimately contains the device name, so the check below is
            // scoped to the table rather than the whole page - a naive
            // whole-page substring check would false-positive on the toast
            // even when the list itself is correctly empty.
            await waitForText(page, "No devices on record");
            const table = await page.$("table");
            assert.equal(table, null, "a device table is still rendered after deleting the only device");

            assertNoPageErrors(page);
        } finally {
            await context.close();
        }
    });
});
