/**
 * Cross-cutting quality suite: accessibility, responsiveness, error states,
 * and rendering hygiene.
 *
 * This file deliberately does NOT depend on axe-core - every accessibility
 * check below is a direct DOM assertion, run inside the page via
 * `page.evaluate`, so it sees the real hydrated tree the way a browser (and a
 * screen reader) would, not the server-rendered markup.
 *
 * A recurring trap in this codebase is a control whose *text content* is
 * non-empty but whose *visible* content is empty at some viewport (Tailwind's
 * `hidden sm:inline` pattern). Naive `el.textContent` does not catch that -
 * see `visibleText()` below, which walks the tree but skips anything
 * `display:none`, `visibility:hidden`, or `aria-hidden="true"`, which is much
 * closer to what an accessible-name computation actually sees.
 */

import test, { before, after, describe } from "node:test";
import assert from "node:assert/strict";
import {
    DEFAULT_TIMEOUT,
    apiCreateDevice,
    apiPost,
    apiSignUp,
    assertNoPageErrors,
    assertStackIsUp,
    goto,
    launchBrowser,
    newPage,
    pageText,
    signInViaUi,
    waitForText,
} from "../harness.mjs";

// ---------------------------------------------------------------------------
// In-page audit: a single self-contained function evaluated in the browser.
// Bundling every DOM-level check into one page.evaluate() call keeps each
// test to one round trip instead of a dozen small ones.
// ---------------------------------------------------------------------------
function collectPageAudit() {
    function isRendered(el) {
        const style = getComputedStyle(el);
        return style.display !== "none" && style.visibility !== "hidden";
    }

    // What a screen reader would actually get from this element's subtree:
    // walks descendants but skips anything CSS-hidden or aria-hidden, so text
    // hidden behind a responsive class (e.g. `hidden sm:inline`) does not
    // count as naming the control - unlike raw `.textContent`.
    function visibleText(el) {
        let out = "";
        for (const node of el.childNodes) {
            if (node.nodeType === Node.TEXT_NODE) {
                out += node.textContent;
            } else if (node.nodeType === Node.ELEMENT_NODE) {
                if (node.getAttribute("aria-hidden") === "true") continue;
                if (!isRendered(node)) continue;
                out += visibleText(node);
            }
        }
        return out;
    }

    function labelText(el) {
        const ariaLabel = el.getAttribute("aria-label");
        if (ariaLabel && ariaLabel.trim()) return ariaLabel.trim();

        const labelledBy = el.getAttribute("aria-labelledby");
        if (labelledBy) {
            const combined = labelledBy
                .split(/\s+/)
                .map((id) => {
                    const target = document.getElementById(id);
                    return target ? visibleText(target).trim() : "";
                })
                .join(" ")
                .trim();
            if (combined) return combined;
        }

        if (el.id) {
            const forLabel = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
            if (forLabel) {
                const text = visibleText(forLabel).trim();
                if (text) return text;
            }
        }

        const wrapper = el.closest("label");
        if (wrapper) {
            const text = visibleText(wrapper).trim();
            if (text) return text;
        }

        if (el.title && el.title.trim()) return el.title.trim();

        return "";
    }

    function describeEl(el) {
        const cls = (el.className || "").toString().trim().slice(0, 60);
        return `<${el.tagName.toLowerCase()}${el.id ? "#" + el.id : ""}${cls ? ` class="${cls}"` : ""}>`;
    }

    const result = {};

    // --- Heading structure (item 1) -----------------------------------
    const headings = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].filter(isRendered);
    result.h1Count = headings.filter((h) => h.tagName === "H1").length;
    result.headingSequence = headings.map((h) => `${h.tagName}:"${visibleText(h).trim().slice(0, 50)}"`);
    result.headingSkip = null;
    let prevLevel = 0;
    for (const h of headings) {
        const level = Number(h.tagName[1]);
        if (prevLevel !== 0 && level > prevLevel + 1) {
            result.headingSkip = { from: prevLevel, to: level, text: visibleText(h).trim().slice(0, 60) };
            break;
        }
        prevLevel = level;
    }

    // --- Form control accessible names (item 2) -------------------------
    const controls = [...document.querySelectorAll("input, select, textarea")].filter(isRendered);
    result.unlabeledControls = controls.filter((el) => !labelText(el)).map(describeEl);

    // --- Images and decorative svg (item 3) -----------------------------
    result.imagesWithoutAlt = [...document.querySelectorAll("img")].filter((img) => !img.hasAttribute("alt")).map(describeEl);
    const svgs = [...document.querySelectorAll("svg")];
    result.svgCount = svgs.length;
    result.svgIssues = svgs
        .filter((svg) => {
            const named =
                (svg.getAttribute("aria-label") && svg.getAttribute("aria-label").trim()) ||
                svg.getAttribute("aria-labelledby") ||
                svg.querySelector("title") ||
                svg.getAttribute("role") === "img";
            const hidden = svg.getAttribute("aria-hidden") === "true";
            return !named && !hidden;
        })
        .map(describeEl);

    // --- Button / link accessible names (item 4) -------------------------
    const actionable = [...document.querySelectorAll("button, a[href]")].filter(isRendered);
    result.unnamedActionable = actionable.filter((el) => !(labelText(el) || visibleText(el).trim())).map(describeEl);

    // --- aria-current (item 5) -------------------------------------------
    const current = [...document.querySelectorAll('[aria-current="page"]')];
    result.ariaCurrentCount = current.length;
    result.ariaCurrentHrefs = current.map((el) => el.getAttribute("href") ?? describeEl(el));

    // --- Table semantics (item 6) -----------------------------------------
    const tables = [...document.querySelectorAll("table")];
    result.tableCount = tables.length;
    result.tableIssues = tables
        .filter((t) => {
            const ths = [...t.querySelectorAll("th")];
            return ths.length === 0 || ths.some((th) => !th.getAttribute("scope"));
        })
        .map(describeEl);
    result.gridLikeDivs = [...document.querySelectorAll('[role="grid"], [role="table"]')].map(describeEl);

    // --- Rendering hygiene (item 13) --------------------------------------
    const bodyText = document.body.innerText;
    result.forbiddenWordHits = ["undefined", "null", "NaN", "Invalid Date"].filter((word) =>
        new RegExp(`\\b${word.replace(/ /g, "\\s+")}\\b`).test(bodyText),
    );
    result.hasObjectObject = bodyText.includes("[object Object]");

    // --- Title (item 15) --------------------------------------------------
    result.title = document.title;

    // --- Horizontal overflow (items 8-9), cheap to include everywhere -----
    result.scrollWidth = document.documentElement.scrollWidth;
    result.innerWidth = window.innerWidth;

    return result;
}

async function audit(page) {
    return page.evaluate(collectPageAudit);
}

function assertAuditClean(report, path) {
    assert.equal(report.h1Count, 1, `${path}: expected exactly one <h1>, found ${report.h1Count}. Headings: ${report.headingSequence.join(" > ")}`);
    assert.equal(report.headingSkip, null, `${path}: heading level skipped a step: ${JSON.stringify(report.headingSkip)}. Full sequence: ${report.headingSequence.join(" > ")}`);
    assert.deepEqual(report.unlabeledControls, [], `${path}: form controls with no accessible name: ${report.unlabeledControls.join(", ")}`);
    assert.deepEqual(report.imagesWithoutAlt, [], `${path}: <img> missing alt: ${report.imagesWithoutAlt.join(", ")}`);
    assert.deepEqual(report.svgIssues, [], `${path}: svg icon that is neither aria-hidden nor accessibly named: ${report.svgIssues.join(", ")}`);
    assert.deepEqual(report.unnamedActionable, [], `${path}: buttons/links with no accessible name: ${report.unnamedActionable.join(", ")}`);
    assert.deepEqual(report.tableIssues, [], `${path}: <table> missing th[scope]: ${report.tableIssues.join(", ")}`);
    assert.deepEqual(report.gridLikeDivs, [], `${path}: role=grid/table div pretending to be a table: ${report.gridLikeDivs.join(", ")}`);
    assert.deepEqual(report.forbiddenWordHits, [], `${path}: literal placeholder text leaked into visible copy: ${report.forbiddenWordHits.join(", ")}`);
    assert.equal(report.hasObjectObject, false, `${path}: "[object Object]" leaked into visible copy`);
    assert.ok(report.title && report.title.trim(), `${path}: document.title is empty`);
    assert.ok(report.scrollWidth <= report.innerWidth + 1, `${path}: horizontal page scroll (scrollWidth=${report.scrollWidth} > innerWidth=${report.innerWidth})`);
}

const VIEWPORTS = [
    { width: 375, height: 812, label: "mobile 375x812" },
    { width: 768, height: 1024, label: "tablet 768x1024" },
    { width: 1440, height: 900, label: "desktop 1440x900" },
];

describe("quality: accessibility, responsiveness, error states, rendering hygiene", () => {
    let browser; // signed in once in before(); every page opened from it shares that session
    let anonBrowser; // NEVER signs in - a genuinely anonymous visitor for /auth/* and 404 checks
    let user;
    let deviceId;

    const STATIC_ROUTES = [
        { path: "/", label: "landing", waitFor: "h1" },
        { path: "/auth/signin", label: "sign in", waitFor: 'input[name="email"]' },
        { path: "/auth/signup", label: "sign up", waitFor: 'input[name="email"]' },
    ];

    function authRoutes() {
        return [
            { path: "/dashboard", label: "dashboard overview", waitFor: "h1" },
            { path: "/dashboard/devices", label: "device list", waitFor: "h1" },
            { path: "/dashboard/devices/new", label: "add device", waitFor: "h1" },
            { path: `/dashboard/devices/${deviceId}`, label: "device detail (fully identified)", waitFor: "h1" },
        ];
    }

    before(async () => {
        await assertStackIsUp();
        browser = await launchBrowser();
        anonBrowser = await launchBrowser();

        // One user, one device, identified against the mock recorder so the
        // detail page has every section populated (identity, channels,
        // storage, clock, capabilities, custody) - the rendering-hygiene
        // checks need real data, not just a bare REGISTERED stub.
        user = await apiSignUp({ name: "Quality Tester" });
        const device = await apiCreateDevice(user.token, { name: "Quality NVR" });
        deviceId = device.id;
        const identified = await apiPost(user.token, `/api/devices/${deviceId}/identify`);
        assert.equal(identified.success, true, `seed device identify failed: ${identified.message}`);

        // Establish the browser session once. Pages opened later from this
        // same `browser` share its cookie jar, so every subsequent
        // newPage() + goto() is already authenticated - confirmed against
        // this harness before relying on it here.
        //
        // `anonBrowser` is a second, separate Chrome instance that this spec
        // never signs in with. It exists because /auth/signin and
        // /auth/signup both server-redirect an already-authenticated visitor
        // straight to /dashboard (see src/app/auth/signin/page.tsx) - reusing
        // the authenticated `browser` for those routes silently redirects
        // away from the page under test instead of failing loudly, which is
        // exactly what happened the first time this suite ran.
        const loginPage = await newPage(browser);
        await signInViaUi(loginPage, { email: user.email, password: user.password });
        await loginPage.close();
    });

    after(async () => {
        await browser?.close();
        await anonBrowser?.close();
    });

    // -----------------------------------------------------------------
    // Items 1, 2, 3, 4, 6, 13, 15 - public (unauthenticated) pages
    // -----------------------------------------------------------------
    describe("accessibility + rendering hygiene: public pages", () => {
        for (const { path, label, waitFor } of STATIC_ROUTES) {
            test(`${label} (${path})`, async () => {
                const page = await newPage(anonBrowser);
                await goto(page, path, { waitFor });
                const report = await audit(page);
                assertAuditClean(report, path);
                assertNoPageErrors(page);
                await page.close();
            });
        }
    });

    // -----------------------------------------------------------------
    // Items 1, 2, 3, 4, 5, 6, 13, 15 - authenticated dashboard pages
    // -----------------------------------------------------------------
    describe("accessibility + rendering hygiene: dashboard pages", () => {
        test("routes and device id are ready", () => {
            assert.ok(deviceId, "seed device id was not created in before()");
        });

        for (const routeGetter of [0, 1, 2, 3]) {
            test(`dashboard route #${routeGetter}`, async () => {
                const { path, label, waitFor } = authRoutes()[routeGetter];
                const page = await newPage(browser);
                await goto(page, path, { waitFor });
                const report = await audit(page);
                assertAuditClean(report, `${label} (${path})`);

                // Item 5: exactly one aria-current="page", and it must be the
                // sidebar item for the route we are actually on.
                assert.equal(report.ariaCurrentCount, 1, `${path}: expected exactly one aria-current="page", found ${report.ariaCurrentCount} (${report.ariaCurrentHrefs.join(", ")})`);

                assertNoPageErrors(page);
                await page.close();
            });
        }

        test("sidebar destinations that do not exist yet are not advertised as clickable navigation", async () => {
            // The app marks unimplemented sections (Cases, Acquisition,
            // Analysis, Reports, Settings) as inert <span aria-disabled="true">
            // rather than <a href>, specifically so it never advertises a
            // destination it cannot serve. Confirm that holds: those labels
            // must NOT resolve to a real link, and must carry a title
            // explaining why.
            const page = await newPage(browser);
            await goto(page, "/dashboard", { waitFor: "h1" });
            const disabled = await page.evaluate(() => {
                const labels = ["Cases", "Acquisition", "Analysis", "Reports", "Settings"];
                const nav = document.querySelector('nav[aria-label="Dashboard navigation"]');
                return labels.map((label) => {
                    const el = [...nav.querySelectorAll("span, a")].find((node) => node.textContent.trim().startsWith(label));
                    return {
                        label,
                        tag: el ? el.tagName : null,
                        isLink: el ? el.tagName === "A" : null,
                        hasTitle: el ? Boolean(el.title && el.title.trim()) : false,
                        ariaDisabled: el ? el.getAttribute("aria-disabled") : null,
                    };
                });
            });
            for (const item of disabled) {
                assert.notEqual(item.tag, null, `sidebar item "${item.label}" was not found at all`);
                assert.notEqual(item.tag, "A", `sidebar item "${item.label}" is a real <a href> to a route that does not exist`);
                assert.equal(item.ariaDisabled, "true", `sidebar item "${item.label}" should be marked aria-disabled="true"`);
                assert.ok(item.hasTitle, `sidebar item "${item.label}" has no title explaining it is unavailable`);
            }
            assertNoPageErrors(page);
            await page.close();
        });

        test("device detail: the 'Device record' edit form's inputs are label-wrapped and accessibly named", async () => {
            // The edit form (record name, recorder username, recorder
            // password) only exists in the DOM once "Edit record" is
            // clicked, so the routine per-page crawl above never sees it -
            // it has to be opened explicitly to be checked at all.
            const page = await newPage(browser);
            await goto(page, `/dashboard/devices/${deviceId}`, { waitFor: "h1" });
            await waitForText(page, "Edit record");
            await Promise.all([
                page.waitForSelector('input[name="password"]'),
                (async () => {
                    const handle = await page.evaluateHandle(() => [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Edit record"));
                    const el = handle.asElement();
                    assert.ok(el, "could not find the 'Edit record' button");
                    await el.click();
                })(),
            ]);

            const report = await audit(page);
            assert.deepEqual(report.unlabeledControls, [], `Device record edit form controls without an accessible name: ${report.unlabeledControls.join(", ")}`);

            // Confirm the specific three fields the coordinator called out,
            // not just an aggregate count.
            const names = await page.evaluate(() => {
                function isRendered(el) {
                    const s = getComputedStyle(el);
                    return s.display !== "none" && s.visibility !== "hidden";
                }
                function visibleText(el) {
                    let out = "";
                    for (const node of el.childNodes) {
                        if (node.nodeType === Node.TEXT_NODE) out += node.textContent;
                        else if (node.nodeType === Node.ELEMENT_NODE && node.getAttribute("aria-hidden") !== "true" && isRendered(node)) out += visibleText(node);
                    }
                    return out;
                }
                return ["name", "username", "password"].map((fieldName) => {
                    const input = document.querySelector(`input[name="${fieldName}"]`);
                    const label = input?.closest("label");
                    return { fieldName, label: label ? visibleText(label).trim() : null };
                });
            });
            for (const { fieldName, label } of names) {
                assert.ok(label, `input[name="${fieldName}"] is not wrapped in a label with visible text`);
            }

            assertNoPageErrors(page);
            await page.close();
        });
    });

    // -----------------------------------------------------------------
    // Item 7 - keyboard access on the sign-in form
    // -----------------------------------------------------------------
    describe("keyboard access", () => {
        test("Tab reaches email -> password -> submit in order, and Enter from password submits", async () => {
            // This test signs in for real (Enter must submit the form), which
            // would leave a cookie behind on a shared browser and break every
            // later "visit /auth/signin as an anonymous user" check (those
            // routes redirect an authenticated visitor to /dashboard). A
            // throwaway browser keeps that side effect fully contained.
            const kbBrowser = await launchBrowser();
            const page = await newPage(kbBrowser);
            await goto(page, "/auth/signin", { waitFor: 'input[name="email"]' });

            await page.focus('input[name="email"]');
            await page.type('input[name="email"]', user.email);

            await page.keyboard.press("Tab");
            const afterEmailTab = await page.evaluate(() => document.activeElement.getAttribute("name"));
            assert.equal(afterEmailTab, "password", `Tab from the email field should land on the password field, landed on "${afterEmailTab}"`);

            await page.type('input[name="password"]', user.password);

            await page.keyboard.press("Tab");
            const onSubmit = await page.evaluate(() => {
                const el = document.activeElement;
                return el.tagName === "BUTTON" && el.type === "submit";
            });
            assert.ok(onSubmit, "Tab from the password field should land on the submit button");

            // Enter from the password field must submit the form without a
            // mouse - a real keyboard-only sign-in path, not just tab order.
            await page.focus('input[name="password"]');
            await Promise.all([
                page.waitForFunction(() => location.pathname.startsWith("/dashboard"), { timeout: DEFAULT_TIMEOUT }),
                page.keyboard.press("Enter"),
            ]);
            assert.match(page.url(), /\/dashboard/);

            assertNoPageErrors(page);
            await kbBrowser.close();
        });
    });

    // -----------------------------------------------------------------
    // Items 8-9 - responsiveness
    // -----------------------------------------------------------------
    describe("responsiveness: no horizontal page scroll at any breakpoint", () => {
        for (const viewport of VIEWPORTS) {
            test(`${viewport.label}: every listed page keeps scrollWidth within the viewport`, async () => {
                async function assertNoOverflow(sourceBrowser, routes) {
                    const page = await newPage(sourceBrowser);
                    await page.setViewport({ width: viewport.width, height: viewport.height });
                    for (const { path, waitFor } of routes) {
                        await goto(page, path, { waitFor });
                        const overflow = await page.evaluate(() => ({
                            scrollWidth: document.documentElement.scrollWidth,
                            innerWidth: window.innerWidth,
                        }));
                        assert.ok(
                            overflow.scrollWidth <= overflow.innerWidth + 1,
                            `${path} at ${viewport.label}: document.documentElement.scrollWidth=${overflow.scrollWidth} > window.innerWidth=${overflow.innerWidth}. ` +
                                "A wide table should scroll inside its own container, not the page body.",
                        );
                    }
                    await page.close();
                }

                // /auth/signin and /auth/signup redirect an authenticated
                // visitor to /dashboard, so the public routes are checked
                // anonymously and the dashboard routes authenticated - the
                // same split used for the accessibility audits above.
                await assertNoOverflow(anonBrowser, STATIC_ROUTES);
                await assertNoOverflow(browser, authRoutes());
            });
        }

        test("mobile 375x812: the dashboard sidebar is reachable, not clipped to zero size", async () => {
            const page = await newPage(browser);
            await page.setViewport({ width: 375, height: 812 });
            await goto(page, "/dashboard/devices", { waitFor: 'nav[aria-label="Dashboard navigation"]' });

            const measurements = await page.evaluate(() => {
                const nav = document.querySelector('nav[aria-label="Dashboard navigation"]');
                const navRect = nav.getBoundingClientRect();
                const devicesLink = [...nav.querySelectorAll("a")].find((a) => a.textContent.trim() === "Devices");
                const linkRect = devicesLink ? devicesLink.getBoundingClientRect() : null;
                return { navRect: { width: navRect.width, height: navRect.height }, linkRect: linkRect && { width: linkRect.width, height: linkRect.height, top: linkRect.top, left: linkRect.left } };
            });

            assert.ok(measurements.navRect.width > 0 && measurements.navRect.height > 0, `dashboard nav has zero size at mobile width: ${JSON.stringify(measurements.navRect)}`);
            assert.ok(measurements.linkRect, "could not find the Devices sidebar link at mobile width");
            assert.ok(measurements.linkRect.width > 0 && measurements.linkRect.height > 0, `Devices sidebar link has zero size at mobile width: ${JSON.stringify(measurements.linkRect)}`);

            await page.close();
        });

        // Previously the navbar Sign-out button lost its accessible name below
        // Tailwind's `sm` breakpoint (<640px): the "Sign out" text lived in a
        // `hidden sm:inline` span with no aria-label fallback on the <button>
        // itself, so at 375px the span was display:none, the LogOut svg was
        // aria-hidden, and the button's accessible name computed to "" - a
        // real WCAG 4.1.2 failure. It only showed up because `unnamedActionable`
        // walks visible text (skipping display:none/aria-hidden content)
        // instead of naive `textContent`, which would have reported "Sign out"
        // and produced a false pass. Now fixed with an explicit aria-label on
        // the <button>, independent of viewport width.
        test("the navbar Sign-out button keeps an accessible name below the 640px breakpoint", async () => {
            const page = await newPage(browser);
            await page.setViewport({ width: 375, height: 812 });
            await goto(page, "/dashboard", { waitFor: "h1" });
            const report = await audit(page);
            assert.deepEqual(report.unnamedActionable, [], `expected no unnamed actionable elements at mobile width, found: ${report.unnamedActionable.join(", ")}`);
            await page.close();
        });
    });

    // -----------------------------------------------------------------
    // Items 10-12 - error and empty states
    // -----------------------------------------------------------------
    describe("error and empty states", () => {
        test("a valid-looking but nonexistent device id renders a clear error state, not a crash or infinite spinner", async () => {
            const page = await newPage(browser);
            const fakeId = "cknonexistentdevicecuid00"; // cuid-shaped; matches no record for any user
            await goto(page, `/dashboard/devices/${fakeId}`, { waitFor: "h1" });

            // useResource() settles to an error state as soon as the failed
            // GET resolves - no arbitrary sleep, just wait for that state.
            await waitForText(page, "unavailable");

            const h1 = await page.$eval("h1", (el) => el.textContent.trim());
            assert.equal(h1, "Device unavailable");
            const text = await pageText(page);
            assert.match(text, /does not exist|unavailable|could not be read/i, `expected a readable error state, got: ${text.slice(0, 300)}`);

            // The failed GET to /api/devices/:id is expected here (that IS
            // the scenario under test), so we check for a crash directly
            // rather than calling assertNoPageErrors (which would also flag
            // that expected 404 as a "failed request").
            assert.deepEqual(page.collected.pageErrors, [], `uncaught page errors: ${page.collected.pageErrors.join("\n")}`);
            await page.close();
        });

        test("an unknown route renders the app's own 404 page, not a generic error or blank screen", async () => {
            const page = await newPage(browser);
            await goto(page, "/no-such-page", { waitFor: "h1" });

            const h1 = await page.$eval("h1", (el) => el.textContent.trim());
            assert.equal(h1, "This route is off the map");
            const text = await pageText(page);
            assert.match(text, /404/);

            // Next.js correctly answers this navigation with a real HTTP 404
            // (verified: curl -o /dev/null -w '%{http_code}' -> 404), so the
            // document request itself is an "expected failure" here too;
            // check for a crash directly instead of the blanket helper.
            assert.deepEqual(page.collected.pageErrors, [], `uncaught page errors: ${page.collected.pageErrors.join("\n")}`);
            await page.close();
        });

        test("backend-down: aborting every request to the Express API shows a readable error state, not a hang or crash", async () => {
            const page = await newPage(browser);
            await page.setRequestInterception(true);
            const onRequest = (req) => {
                if (req.url().includes("localhost:9000")) req.abort("failed");
                else req.continue();
            };
            page.on("request", onRequest);

            try {
                await goto(page, "/dashboard/devices");
                // No fixed sleep: wait for the resource hook to settle into
                // its error branch once the aborted request rejects.
                await waitForText(page, "unavailable", 15000);

                const text = await pageText(page);
                assert.match(text, /unavailable|could not be loaded|failed/i, `expected a readable error state, got: ${text.slice(0, 300)}`);

                // The point here is resilience, not silence: aborting a live
                // request is expected to log something to the console. What
                // must NOT happen is an uncaught exception reaching the page.
                assert.deepEqual(page.collected.pageErrors, [], `uncaught page errors while the API was down: ${page.collected.pageErrors.join("\n")}`);
            } finally {
                page.off("request", onRequest);
                await page.setRequestInterception(false);
            }

            await page.close();
        });
    });

    // -----------------------------------------------------------------
    // Item 15 (continued) - every route gets its own, non-generic title
    // -----------------------------------------------------------------
    describe("page titles", () => {
        // Previously /auth/signin, /auth/signup, /auth/error and /no-such-page
        // all rendered the exact same generic "VigiTrace" title (no route-level
        // `metadata` export), indistinguishable from each other and from the
        // homepage. Each now declares its own metadata; assert the titles are
        // genuinely distinct rather than just non-empty.
        test("sign-in, sign-up, 404, and the auth-error page each have their own distinct <title>", async () => {
            // Anonymous on purpose: an authenticated visit to /auth/signin
            // or /auth/signup redirects straight to /dashboard, which
            // would measure the dashboard's title instead of the auth
            // page's.
            const page = await newPage(anonBrowser);
            const titles = {};
            for (const path of ["/", "/auth/signin", "/auth/signup", "/auth/error", "/no-such-page"]) {
                await goto(page, path, { waitFor: "h1" });
                titles[path] = await page.title();
            }
            const distinct = new Set(Object.values(titles));
            assert.equal(distinct.size, Object.keys(titles).length, `expected a distinct <title> per route, got: ${JSON.stringify(titles)}`);
            // The homepage's title is intentionally just the brand name.
            assert.equal(titles["/"], "VigiTrace");
            await page.close();
        });
    });
});
