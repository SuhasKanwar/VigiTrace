import test, { before, after, describe } from "node:test";
import assert from "node:assert/strict";
import {
    CLIENT_URL,
    assertNoPageErrors,
    assertStackIsUp,
    launchBrowser,
    newPage,
    pageText,
} from "../harness.mjs";

describe("smoke", () => {
    let browser;
    before(async () => {
        await assertStackIsUp();
        browser = await launchBrowser();
    });
    after(async () => browser?.close());

    test("the landing page renders its hero and wordmark", async () => {
        const page = await newPage(browser);
        await page.goto(CLIENT_URL, { waitUntil: "networkidle2" });
        assert.equal(await page.title(), "VigiTrace");
        const heading = await page.$eval("h1", (el) => el.textContent);
        assert.match(heading, /Trace every frame/i);
        assertNoPageErrors(page);
        await page.close();
    });

    test("an unauthenticated visit to the dashboard is redirected to sign-in", async () => {
        const page = await newPage(browser);
        await page.goto(`${CLIENT_URL}/dashboard`, { waitUntil: "networkidle2" });
        assert.match(page.url(), /\/auth\/signin/);
        assert.doesNotMatch(await pageText(page), /Chain of custody/i);
        await page.close();
    });
});
