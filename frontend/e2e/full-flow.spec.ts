import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

// The 18-step product flow against the real stack (stub LLM for /ask):
//  1 register  2 log in  3 upload a PDF  4 watch the status change  5 completed
//  6 search shows extracted text  7 ask shows an answer  8 with citations
//  9 log out  10 log in again  11 documents remain  12 a second user registers
// 13 cannot see the first user's document in the list  14 nor open it by URL
// 15 nor find it in search  16 the session cookie is HttpOnly (no token in JS storage)
// 17 delete the document  18 it is gone (list and direct URL)

// Screenshots land in frontend/e2e-screenshots/ (git-ignored); docs/screenshots/ holds a
// curated, hand-picked subset. Set E2E_SCREENSHOT_DIR to write elsewhere.
const SCREENSHOTS = process.env.E2E_SCREENSHOT_DIR ?? path.resolve(__dirname, "../e2e-screenshots");
const FIXTURES = path.resolve(__dirname, "fixtures");
const PASSWORD = "e2e-password-1234";
const runId = Date.now().toString(36);
const userA = `alice-${runId}@example.com`;
const userB = `bob-${runId}@example.com`;

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(SCREENSHOTS, `${name}.png`), fullPage: true });
}

async function register(page: Page, email: string) {
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByTestId("user-email")).toHaveText(email);
}

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

async function logout(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).first().click();
  await expect(page).toHaveURL(/\/login\?reason=signed-out/);
  await expect(page.getByText("You have been signed out.")).toBeVisible();
}

async function newPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1366, height: 900 } });
  return context.newPage();
}

test.describe.configure({ mode: "serial" });

let documentId = "";
let pageA: Page;

test("public pages render", async ({ browser }) => {
  const page = await newPage(browser);
  await page.goto("/");
  await expect(page).toHaveTitle("Document Intelligence & Analysis");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Document Intelligence & Analysis",
  );
  await expect(page.getByRole("img", { name: "Document Intelligence & Analysis" }).first()).toBeVisible();
  await expect(page.getByRole("contentinfo")).toContainText(/© \d{4} Document Intelligence & Analysis/);
  await shot(page, "landing");
  // Every public link on the landing page resolves (no 404s).
  const hrefs = await page.$$eval("a[href^='/']", (as) => [...new Set(as.map((a) => a.getAttribute("href")!.split("#")[0] || "/"))]);
  for (const href of hrefs) expect((await page.request.get(href)).status(), href).toBe(200);
  expect((await page.request.get("/architecture")).status()).toBe(404);
  // Protected pages redirect to the login page without a session.
  await page.goto("/documents");
  await expect(page).toHaveURL(/\/login\?next=%2Fdocuments/);
  await page.context().close();
});

test("1-2: register, log out and log in", async ({ browser }) => {
  pageA = await newPage(browser);
  await register(pageA, userA);
  await logout(pageA);
  await login(pageA, userA);
  await expect(pageA.getByTestId("count-total")).toHaveText("0");
});

test("3-5: upload a PDF and watch it complete", async () => {
  const page = pageA;
  await page.goto("/upload");
  await expect(page.getByText("Drag and drop files here")).toBeVisible();

  // Pre-validation against the backend allowlist: nothing is sent for a .csv file.
  await page.getByTestId("file-input").setInputFiles(path.join(FIXTURES, "notes.csv"));
  await expect(page.getByText(/Unsupported file type ".csv"/)).toBeVisible();

  const uploadRequest = page.waitForRequest(
    (req) => req.method() === "POST" && req.url() === `${process.env.E2E_API_URL ?? "http://localhost:8000"}/documents`,
  );
  await page.getByTestId("file-input").setInputFiles(path.join(FIXTURES, "refund-policy.pdf"));
  const sent = await uploadRequest;
  // Direct upload with the short-lived upload token, never the session cookie.
  expect(sent.headers()["authorization"]).toMatch(/^Bearer /);
  expect(sent.headers()["cookie"]).toBeUndefined();

  const item = page.getByTestId("upload-item").filter({ hasText: "refund-policy.pdf" });
  const seen = new Set<string>();
  const badge = item.getByTestId("status-badge");
  await expect(badge).toBeVisible({ timeout: 30_000 });
  await expect
    .poll(
      async () => {
        const status = await badge.getAttribute("data-status");
        if (status) seen.add(status);
        return status;
      },
      { timeout: 180_000, intervals: [250] },
    )
    .toBe("completed");
  expect([...seen].some((s) => ["queued", "processing", "uploaded"].includes(s))).toBe(true);
  await expect(item.getByText(/chunks indexed/)).toBeVisible();
  await shot(page, "upload");

  const href = await item.getByRole("link", { name: "View" }).getAttribute("href");
  documentId = href?.split("/").pop() ?? "";
  expect(documentId).toMatch(/^[0-9a-f-]{36}$/);

  await page.goto("/dashboard");
  await expect(page.getByTestId("count-completed")).toHaveText("1");
  await expect(page.getByTestId("count-total")).toHaveText("1");
  await shot(page, "dashboard");

  await page.goto("/documents");
  await expect(page.getByTestId("document-row")).toHaveCount(1);
  await shot(page, "documents");

  await page.goto(`/documents/${documentId}`);
  await expect(page.getByTestId("chunk-count")).not.toHaveText("0");
  await shot(page, "document-detail");
});

test("6: search shows real extracted text", async () => {
  const page = pageA;
  await page.goto("/search");
  await page.getByLabel("Search query").fill("return unused items within 30 days");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  const first = page.getByTestId("search-result").first();
  await expect(first).toContainText("Customers may return unused items within 30 days of delivery");
  await expect(first).toContainText("refund-policy.pdf");
  await expect(first).toContainText(/pages? 1/);
  await shot(page, "search");
});

test("7-8: ask shows a clean Markdown answer; citations stay in the API response (stub LLM)", async () => {
  const page = pageA;
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/ask");
  await page.getByLabel("Your question").fill("How many days do customers have to return unused items?");
  const reply = page.waitForResponse((r) => r.url().includes("/api/proxy/ask") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const body = await (await reply).json();
  // Grounding metadata is still returned by the API; the text itself has no markers.
  expect(body.citations.length).toBeGreaterThan(0);
  expect(body.citations[0].filename).toBe("refund-policy.pdf");
  expect(body.answer).not.toMatch(/\[\d+\]/);
  const answer = page.getByTestId("answer");
  await expect(answer.getByRole("heading", { level: 2, name: "Answer" })).toBeVisible();
  await expect(answer.getByRole("heading", { level: 4, name: "Summary" })).toBeVisible();
  await expect(answer).toContainText("The document states");
  await expect(answer).toContainText("30 days");
  const text = await answer.innerText();
  expect(text).not.toMatch(/\[\d+\]|Sources|retrieved passage|gpt-|Partial|Show cited passage/);
  await expect(answer.getByTestId("citation")).toHaveCount(0);
  await expect(page.getByTestId("question-bubble")).toContainText("return unused items");
  await answer.getByTestId("copy-answer").click();
  await expect(answer.getByTestId("copy-answer")).toHaveText("Copied");
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toContain("The document states");
  expect(copied).not.toMatch(/\[\d+\]|Sources/);
  await expect(page.getByText("AI answers can be wrong")).toBeVisible();
  await shot(page, "ask");
});

test("9-11: log out, log in again, documents remain", async () => {
  const page = pageA;
  await logout(page);
  await login(page, userA);
  await page.goto("/documents");
  await expect(page.getByTestId("document-row")).toHaveCount(1);
  await expect(page.getByTestId("document-row").first()).toContainText("refund-policy.pdf");
});

test("12-15: a second user cannot see, open or search the first user's document", async ({ browser }) => {
  const page = await newPage(browser);
  await register(page, userB);
  await page.goto("/documents");
  await expect(page.getByText("No documents", { exact: true })).toBeVisible();
  await page.goto(`/documents/${documentId}`);
  await expect(page.locator("main").getByRole("alert")).toContainText("does not exist or you don't have access");
  const direct = await page.request.get(`/api/proxy/documents/${documentId}`);
  expect(direct.status()).toBe(404);
  await page.goto("/search");
  await page.getByLabel("Search query").fill("return unused items within 30 days");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText("No matching passages")).toBeVisible();
  // CSRF: a state-changing call without the custom header is refused by the proxy.
  const forged = await page.request.post("/api/proxy/search", { data: { query: "x" } });
  expect(forged.status()).toBe(403);
  await page.context().close();
});

test("16: the session token is HttpOnly and not in JS-visible storage", async () => {
  const page = pageA;
  const cookies = await page.context().cookies();
  const session = cookies.find((c) => c.name === "dip_session");
  expect(session?.httpOnly).toBe(true);
  expect(session?.sameSite).toBe("Lax");
  expect(session?.secure).toBe(new URL(page.url()).protocol === "https:");
  const visible = await page.evaluate(() => ({
    cookie: document.cookie,
    local: JSON.stringify(window.localStorage),
    session: JSON.stringify(window.sessionStorage),
  }));
  expect(visible.cookie).not.toContain("dip_session");
  expect(visible.local).not.toMatch(/eyJ/);
  expect(visible.session).not.toMatch(/eyJ/);
});

test("mobile layout", async ({ browser }) => {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    storageState: await pageA.context().storageState(),
  });
  const page = await context.newPage();
  await page.goto("/dashboard");
  await expect(page.getByTestId("count-total")).toHaveText("1");
  await shot(page, "mobile-dashboard");
  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.locator("#mobile-nav").getByRole("link", { name: "Ask AI" })).toBeVisible();
  await context.close();
});

test("17-18: delete the document and verify it is gone", async () => {
  const page = pageA;
  await page.goto("/documents");
  await page.getByRole("button", { name: /^Delete refund-policy\.pdf$/ }).click();
  const dialog = page.getByRole("dialog", { name: "Delete document?" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText('Deleted "refund-policy.pdf".')).toBeVisible();
  await expect(page.getByText("No documents", { exact: true })).toBeVisible();
  const gone = await page.request.get(`/api/proxy/documents/${documentId}`);
  expect(gone.status()).toBe(404);
  await page.goto(`/documents/${documentId}`);
  await expect(page.locator("main").getByRole("alert")).toContainText("does not exist");
});
