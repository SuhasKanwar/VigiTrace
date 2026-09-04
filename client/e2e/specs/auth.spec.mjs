import test, { before, after, describe } from "node:test";
import assert from "node:assert/strict";
import {
    CLIENT_URL,
    PASSWORD,
    SERVER_URL,
    apiSignUp,
    assertNoPageErrors,
    assertStackIsUp,
    goto,
    launchBrowser,
    newPage,
    pageText,
    signInViaUi,
    signUpViaUi,
    uniqueEmail,
    waitForText,
} from "../harness.mjs";

/**
 * Every test below signs in, signs out, or both, so each one needs its own
 * cookie jar. Sharing the browser's default context across tests (the way
 * smoke.spec.mjs can, since it never authenticates) would leak a session
 * from one test into the next and make "signed out" tests fail depending on
 * run order. A fresh BrowserContext per test gives a clean slate cheaply.
 */
async function isolatedPage(browser) {
    // `Target.createBrowserContext` occasionally throws
    // "Session with given id not found" - a transient CDP transport hiccup
    // (observed once in ~60 runs, only under heavy concurrent load from other
    // spec files/agents driving the same Chrome install), not a logic error.
    // This retries the CDP call itself; it does not weaken any assertion.
    let lastError;
    for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
            const context = await browser.createBrowserContext();
            // BrowserContext exposes the same newPage() signature newPage() expects.
            return await newPage(context);
        } catch (error) {
            lastError = error;
        }
    }
    throw lastError;
}

async function closePage(page) {
    await page.browserContext().close();
}

/**
 * NextAuth's Credentials provider reports "authorize() rejected" by
 * answering its own callback endpoint (/api/auth/callback/credentials) with
 * an HTTP 401 - the same pattern the harness already allow-lists for
 * /api/auth/session. It is how the provider signals invalid credentials,
 * not an app bug, but assertNoPageErrors() has no allowlist for
 * failedRequests (only consoleErrors), so tests that deliberately trigger a
 * rejected sign-in/sign-up must drop this one expected entry themselves
 * before calling it.
 */
function allowExpectedCredentialsFailure(page) {
    page.collected.failedRequests = page.collected.failedRequests.filter(
        (entry) => !entry.includes("/api/auth/callback/credentials"),
    );
}

/** The avatar in the top nav is the only place identity renders (see report); read its initial. */
async function navAvatarInitial(page) {
    return page.$eval(
        'header a[href="/dashboard"] span',
        (el) => el.textContent.trim(),
    ).catch(() => null);
}

/**
 * Navigate somewhere the app is expected to bounce off of client-side, and
 * wait for the real pathname to land.
 *
 * Every "must redirect" case here (an unauthenticated visit to a protected
 * route, an authenticated visit to /auth/signin|signup, the post-sign-out
 * revisit to /dashboard) is NOT an HTTP 30x - confirmed with curl, the
 * initial response is a 200 whose RSC payload embeds
 * `NEXT_REDIRECT;replace;<path>;307;`, and Next's client router only acts on
 * it after the bundle hydrates. That's also why this bypasses the shared
 * `goto()` helper (harness.mjs) instead of calling it: goto()'s second step,
 * `page.waitForSelector("body")`, resolves a DOM node by id and occasionally
 * loses the race against that same client-side redirect - in stability
 * testing it threw `ProtocolError: Node with given id does not belong to the
 * document` once. This is a shared-harness fragility worth fixing centrally
 * (reported), but since e2e/harness.mjs is out of scope here, this file
 * drives the navigation itself and waits on the one condition that actually
 * matters: the URL the app settles on.
 */
async function gotoExpectingRedirectTo(page, path, expectedPathnamePrefix) {
    const url = path.startsWith("http") ? path : `${CLIENT_URL}${path}`;
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(
        (prefix) => location.pathname.startsWith(prefix),
        { timeout: 20000 },
        expectedPathnamePrefix,
    );
}

describe("auth", () => {
    let browser;
    before(async () => {
        await assertStackIsUp();
        browser = await launchBrowser();
    });
    after(async () => browser?.close());

    describe("sign-up", () => {
        test("happy path creates an account, lands on the dashboard, survives a reload, and shows the user's identity", async () => {
            const page = await isolatedPage(browser);
            const name = "E2E Signup Tester";
            const email = uniqueEmail("signup-happy");
            await signUpViaUi(page, { name, email, password: PASSWORD });

            assert.match(page.url(), /\/dashboard(\/|$)/, "signup should land on the dashboard");

            // The full name/email is never rendered as text anywhere in the
            // authenticated chrome (see report) - the nav avatar's initial
            // letter is the only observable signal that identity flowed
            // through, so that is what regresses if it breaks.
            assert.equal(await navAvatarInitial(page), "E", "nav avatar should show the account's initial");

            // Reloading re-derives auth purely from the persisted session
            // cookie/JWT; if that wiring breaks, a reload bounces to signin.
            await page.reload({ waitUntil: "domcontentloaded" });
            await page.waitForSelector("h1");
            assert.match(page.url(), /\/dashboard(\/|$)/, "session should survive a reload");
            assert.match(await pageText(page), /Sign out/i, "authenticated nav should still show Sign out after reload");

            assertNoPageErrors(page);
            await closePage(page);
        });

        test("rejects an empty submission before any request leaves the browser", async () => {
            const page = await isolatedPage(browser);
            await goto(page, "/auth/signup", { waitFor: 'input[name="name"]' });
            await page.click('button[type="submit"]');
            // The three inputs carry `required`; a real submit attempt with
            // network activity would prove Chrome's own HTML5 validation
            // was bypassed, which is the actual regression this guards.
            await new Promise((resolve) => setTimeout(resolve, 300));

            assert.equal(page.url(), `${CLIENT_URL}/auth/signup`, "an empty submit must not navigate away");
            const nameValidity = await page.$eval('input[name="name"]', (el) => el.validity.valid);
            assert.equal(nameValidity, false, "the required name field should report itself invalid");

            assertNoPageErrors(page);
            await closePage(page);
        });

        test("rejects a malformed email before any request leaves the browser", async () => {
            const page = await isolatedPage(browser);
            await goto(page, "/auth/signup", { waitFor: 'input[name="name"]' });
            await page.type('input[name="name"]', "Bad Email Tester");
            await page.type('input[name="email"]', "not-an-email");
            await page.type('input[name="password"]', PASSWORD);
            await page.click('button[type="submit"]');
            await new Promise((resolve) => setTimeout(resolve, 300));

            assert.equal(page.url(), `${CLIENT_URL}/auth/signup`, "a malformed email must not navigate away");
            const emailValidity = await page.$eval('input[name="email"]', (el) => el.validity.valid);
            assert.equal(emailValidity, false, "the email field's type=\"email\" constraint should reject it");

            assertNoPageErrors(page);
            await closePage(page);
        });

        // The sign-up password field now carries minLength={8}
        // (src/components/auth/auth-form.tsx, sign-up only) and the Express
        // handler enforces the same floor server-side
        // (server/src/controllers/authController.ts describePasswordProblem,
        // MIN_PASSWORD_LENGTH = 8). Both layers matter: the client check is
        // only a convenience, so this asserts the browser blocks the
        // submission AND, independently, that a direct API call gets the
        // exact 400 the server now returns - proving the real gate is
        // server-side, not just a UX nicety that could be bypassed.
        test("rejects a too-short password through the UI's minLength and the API's own check", async () => {
            const page = await isolatedPage(browser);
            const uiEmail = uniqueEmail("short-password-ui");

            await goto(page, "/auth/signup", { waitFor: 'input[name="name"]' });
            await page.type('input[name="name"]', "Short Password Tester");
            await page.type('input[name="email"]', uiEmail);
            await page.type('input[name="password"]', "a");
            await page.click('button[type="submit"]');
            // No `required`-style native tooltip navigation ever fires here;
            // a fixed settle is the only way to prove *nothing* happened.
            await new Promise((resolve) => setTimeout(resolve, 300));

            assert.equal(page.url(), `${CLIENT_URL}/auth/signup`, "a too-short password must not navigate away");
            const passwordValidity = await page.$eval('input[name="password"]', (el) => el.validity.valid);
            assert.equal(passwordValidity, false, "the password field's minLength constraint should reject it");

            const apiRes = await fetch(`${SERVER_URL}/api/auth/signup`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: "API Short Password", email: uniqueEmail("short-password-api"), password: "a" }),
            });
            const apiBody = await apiRes.json();
            assert.equal(apiRes.status, 400, "the API must reject a too-short password too, not just the UI");
            assert.equal(apiBody.success, false);
            assert.equal(apiBody.message, "Password must be at least 8 characters.");

            assertNoPageErrors(page);
            await closePage(page);
        });

        // 8 spaces satisfies minLength={8} (it only counts characters), so
        // the browser lets this one through - the server's
        // describePasswordProblem() whitespace check is the only thing that
        // can still catch it. Driving this through the real form (rather
        // than a bare API call) proves that end-to-end: a client-side-only
        // regression here would silently create an account with an unusable
        // password.
        test("rejects a whitespace-only password server-side even though the UI's minLength lets it through", async () => {
            const page = await isolatedPage(browser);
            const email = uniqueEmail("whitespace-password");

            await goto(page, "/auth/signup", { waitFor: 'input[name="name"]' });
            await page.type('input[name="name"]', "Whitespace Password Tester");
            await page.type('input[name="email"]', email);
            await page.type('input[name="password"]', "        ");

            const passwordValidityBeforeSubmit = await page.$eval('input[name="password"]', (el) => el.validity.valid);
            assert.equal(passwordValidityBeforeSubmit, true, "8 spaces satisfies minLength client-side - the server must be the real gate");

            await page.click('button[type="submit"]');
            await waitForText(page, "Could not create the account");
            assert.match(page.url(), /\/auth\/signup$/, "a whitespace-only password must not navigate to the dashboard");

            const apiRes = await fetch(`${SERVER_URL}/api/auth/signup`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: "API Whitespace Password", email: uniqueEmail("whitespace-password-api"), password: "        " }),
            });
            const apiBody = await apiRes.json();
            assert.equal(apiRes.status, 400);
            assert.equal(apiBody.success, false);
            assert.equal(apiBody.message, "Password cannot be only whitespace.");

            allowExpectedCredentialsFailure(page);
            assertNoPageErrors(page, { allowConsole: ["401 (Unauthorized)"] });
            await closePage(page);
        });

        test("rejects a duplicate email with a visible error and does not navigate to the dashboard", async () => {
            const page = await isolatedPage(browser);
            const { email } = await apiSignUp({ password: PASSWORD });

            await goto(page, "/auth/signup", { waitFor: 'input[name="name"]' });
            await page.type('input[name="name"]', "Duplicate Email Tester");
            await page.type('input[name="email"]', email);
            await page.type('input[name="password"]', PASSWORD);
            await page.click('button[type="submit"]');

            // AuthForm renders its error in an aria-live region rather than a
            // toast (there is no client-side call to the axios `api`
            // instance in this flow - see report), so that is what a
            // duplicate-email regression would actually break.
            await waitForText(page, "Could not create the account");
            assert.match(page.url(), /\/auth\/signup$/, "a rejected signup must not navigate to the dashboard");

            allowExpectedCredentialsFailure(page);
            // NextAuth logs the expected 401 above to the console too.
            assertNoPageErrors(page, { allowConsole: ["401 (Unauthorized)"] });
            await closePage(page);
        });
    });

    describe("sign-in", () => {
        test("happy path signs in an account created via the API and lands on the dashboard", async () => {
            const page = await isolatedPage(browser);
            const { email } = await apiSignUp({ password: PASSWORD });
            await signInViaUi(page, { email, password: PASSWORD });

            assert.match(page.url(), /\/dashboard(\/|$)/);
            assertNoPageErrors(page);
            await closePage(page);
        });

        test("rejects the wrong password with a visible error and stays on sign-in", async () => {
            const page = await isolatedPage(browser);
            const { email } = await apiSignUp({ password: PASSWORD });

            await goto(page, "/auth/signin", { waitFor: 'input[name="email"]' });
            await page.type('input[name="email"]', email);
            await page.type('input[name="password"]', "TotallyWrongPass1!");
            await page.click('button[type="submit"]');

            await waitForText(page, "Email or password is incorrect");
            assert.match(page.url(), /\/auth\/signin$/, "a rejected sign-in must not navigate to the dashboard");

            allowExpectedCredentialsFailure(page);
            assertNoPageErrors(page, { allowConsole: ["401 (Unauthorized)"] });
            await closePage(page);
        });

        test("rejects an unknown email with a visible error and stays on sign-in", async () => {
            const page = await isolatedPage(browser);
            await goto(page, "/auth/signin", { waitFor: 'input[name="email"]' });
            await page.type('input[name="email"]', uniqueEmail("nobody"));
            await page.type('input[name="password"]', "WhoKnows123!");
            await page.click('button[type="submit"]');

            await waitForText(page, "Email or password is incorrect");
            assert.match(page.url(), /\/auth\/signin$/, "an unknown email must not navigate to the dashboard");

            allowExpectedCredentialsFailure(page);
            assertNoPageErrors(page, { allowConsole: ["401 (Unauthorized)"] });
            await closePage(page);
        });
    });

    describe("session and protected routes", () => {
        const protectedRoutes = ["/dashboard", "/dashboard/devices", "/dashboard/devices/new"];

        for (const route of protectedRoutes) {
            test(`signed out, ${route} redirects to sign-in`, async () => {
                const page = await isolatedPage(browser);
                await gotoExpectingRedirectTo(page, route, "/auth/signin");
                assert.match(page.url(), /\/auth\/signin$/, `${route} must redirect an unauthenticated visitor`);
                assertNoPageErrors(page);
                await closePage(page);
            });
        }

        const expectedHeadings = {
            "/dashboard": "Overview",
            "/dashboard/devices": "Devices",
            "/dashboard/devices/new": "Add device",
        };

        for (const route of protectedRoutes) {
            test(`signed in, ${route} renders its real content`, async () => {
                const page = await isolatedPage(browser);
                const { email } = await apiSignUp({ password: PASSWORD });
                await signInViaUi(page, { email, password: PASSWORD });

                await goto(page, route, { waitFor: "h1" });
                assert.equal(page.url(), `${CLIENT_URL}${route}`, `${route} must render in place, not redirect`);
                assert.equal(await page.$eval("h1", (el) => el.textContent), expectedHeadings[route]);

                assertNoPageErrors(page);
                await closePage(page);
            });
        }
    });

    describe("signed-in users are redirected away from the auth pages", () => {
        test("visiting /auth/signin while signed in redirects to the dashboard", async () => {
            const page = await isolatedPage(browser);
            const { email } = await apiSignUp({ password: PASSWORD });
            await signInViaUi(page, { email, password: PASSWORD });

            await gotoExpectingRedirectTo(page, "/auth/signin", "/dashboard");
            assert.match(page.url(), /\/dashboard(\/|$)/, "an authenticated visitor must not see the sign-in form");

            assertNoPageErrors(page);
            await closePage(page);
        });

        test("visiting /auth/signup while signed in redirects to the dashboard", async () => {
            const page = await isolatedPage(browser);
            const { email } = await apiSignUp({ password: PASSWORD });
            await signInViaUi(page, { email, password: PASSWORD });

            await gotoExpectingRedirectTo(page, "/auth/signup", "/dashboard");
            assert.match(page.url(), /\/dashboard(\/|$)/, "an authenticated visitor must not see the sign-up form");

            assertNoPageErrors(page);
            await closePage(page);
        });
    });

    describe("sign-out", () => {
        test("signing out clears the session and /dashboard redirects to sign-in again", async () => {
            const page = await isolatedPage(browser);
            const { email } = await apiSignUp({ password: PASSWORD });
            await signInViaUi(page, { email, password: PASSWORD });

            await goto(page, "/dashboard", { waitFor: "h1" });
            const signOutHandle = await page.evaluateHandle(() =>
                [...document.querySelectorAll("button")].find((el) => /sign ?out/i.test(el.textContent ?? "")),
            );
            const signOutButton = signOutHandle.asElement();
            assert.ok(signOutButton, "expected a Sign out control in the authenticated chrome");

            await Promise.all([
                page.waitForFunction(() => location.pathname === "/", { timeout: 20000 }),
                signOutButton.click(),
            ]);

            assert.doesNotMatch(await pageText(page), /Sign out/i, "the nav should no longer offer to sign out");
            assert.match(await pageText(page), /Sign in/i, "the nav should fall back to the guest state");

            // The real regression this guards: a stale client-side session
            // state could still show "authenticated" while the server-side
            // cookie/JWT is already gone (or vice-versa), so re-request the
            // protected route rather than trusting the nav alone.
            await gotoExpectingRedirectTo(page, "/dashboard", "/auth/signin");
            assert.match(page.url(), /\/auth\/signin$/, "the session must actually be gone server-side too");

            assertNoPageErrors(page);
            await closePage(page);
        });
    });

    describe("token wiring", () => {
        test("the device list request carries a Bearer token and the Express API answers without a 401", async () => {
            const page = await isolatedPage(browser);
            const { email } = await apiSignUp({ password: PASSWORD });
            await signInViaUi(page, { email, password: PASSWORD });

            const deviceApiRequests = [];
            page.on("request", (req) => {
                if (req.url().endsWith("/api/devices") && req.method() === "GET") {
                    deviceApiRequests.push(req.headers()["authorization"] ?? null);
                }
            });
            const deviceApiResponses = [];
            page.on("response", (res) => {
                if (res.url().endsWith("/api/devices")) deviceApiResponses.push(res.status());
            });

            await goto(page, "/dashboard/devices", { waitFor: "h1" });
            // The list resolves asynchronously after the shell renders; wait
            // for the request that matters rather than a fixed sleep.
            await new Promise((resolve, reject) => {
                const started = Date.now();
                const check = () => {
                    if (deviceApiRequests.length > 0) return resolve();
                    if (Date.now() - started > 15000) return reject(new Error("no GET /api/devices request was observed"));
                    setTimeout(check, 100);
                };
                check();
            });

            // This is the regression this test exists to catch: if the axios
            // interceptor in src/lib/api.ts ever stops attaching the
            // Authorization header, every one of these requests goes out
            // unauthenticated and the Express API answers 401.
            assert.ok(
                deviceApiRequests.every((header) => typeof header === "string" && header.startsWith("Bearer ")),
                `expected every /api/devices request to carry "Authorization: Bearer <token>", got: ${JSON.stringify(deviceApiRequests)}`,
            );
            assert.ok(
                deviceApiResponses.every((status) => status !== 401),
                `expected no 401 from /api/devices, got statuses: ${JSON.stringify(deviceApiResponses)}`,
            );
            assert.doesNotMatch(await pageText(page), /unauthorized|unauthenticated/i, "the page must not show an auth error");

            assertNoPageErrors(page);
            await closePage(page);
        });
    });
});
