import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { FIXTURES, MOBILE, newContextPage, presetTheme, shot, watchConsole } from "./helpers";

// Demo mode end to end: landing "Try the demo" → upload one PDF → 3 questions (structured
// stub replies with citations) → the 4th is refused and the "Create a free account to
// continue" modal opens → converting keeps the document and lifts the limits.

test.describe.configure({ mode: "serial" });

let page: Page;
let errors: string[];
let documentId = "";

async function askQuestion(question: string) {
  await page.getByLabel("Your question").fill(question);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByTestId("typing-indicator")).toHaveCount(0, { timeout: 60_000 });
}

test("start a demo from the landing page", async ({ browser }) => {
  page = await newContextPage(browser);
  errors = watchConsole(page);
  await page.goto("/");
  await page.getByTestId("try-demo").first().click();
  await expect(page).toHaveURL(/\/upload\?demo=1$/);
  await expect(page.getByTestId("demo-banner")).toContainText("Demo: 3 of 3 questions left");
  await expect(page.getByTestId("demo-upload-hint")).toContainText("PDF only");
});

test("upload one PDF: Uploading → Processing → Ready, then the Ask CTA", async () => {
  await page.getByTestId("file-input").setInputFiles(path.join(FIXTURES, "refund-policy.pdf"));
  const item = page.getByTestId("upload-item").filter({ hasText: "refund-policy.pdf" });
  await expect(item.getByTestId("upload-stepper")).toBeVisible();
  await expect(item.getByTestId("status-badge")).toHaveAttribute("data-status", "completed", { timeout: 180_000 });
  await expect(item.getByTestId("upload-stepper").locator('[aria-current="step"]')).toContainText("Ready");
  await expect(page.getByTestId("toast").filter({ hasText: "Document ready" })).toBeVisible();
  await shot(page, "demo-upload-ready-dark");
  // The demo allows a single upload; the API refuses a second one (and the modal opens).
  await page.getByTestId("file-input").setInputFiles(path.join(FIXTURES, "refund-policy.pdf"));
  await expect(page.getByTestId("demo-limit-modal")).toBeVisible();
  await expect(page.getByTestId("demo-limit-modal")).toContainText("The demo includes one document.");
  await page.getByRole("button", { name: "Not now" }).click();
  await expect(page.getByTestId("demo-limit-modal")).toBeHidden();

  const cta = item.getByTestId("ask-cta");
  documentId = new URL((await cta.getAttribute("href")) ?? "", "https://x").searchParams.get("document") ?? "";
  expect(documentId).toMatch(/^[0-9a-f-]{36}$/);
  await cta.click();
  await expect(page).toHaveURL(new RegExp(`/ask\\?document=${documentId}$`));
});

test("three questions with cited answers, then the limit modal", async () => {
  await expect(page.getByTestId("starter-question")).toHaveCount(4);
  await askQuestion("How many days do customers have to return unused items?");
  const answer = page.getByTestId("answer").last();
  await expect(answer).toContainText("According to the document");
  await expect(answer).not.toContainText("99");
  await expect(page.getByTestId("demo-banner")).toContainText("2 of 3 questions left");

  // Clicking the [1] chip highlights and expands its source card.
  await answer.getByRole("button", { name: "Citation 1" }).click();
  const source = answer.getByTestId("citation").first();
  await expect(source).toHaveAttribute("data-active", "true");
  await expect(source.locator("blockquote")).toBeVisible();
  await expect(source).toContainText("refund-policy.pdf");
  await shot(page, "ask-citations-dark");

  await page.getByTestId("starter-question").first().waitFor({ state: "detached" });
  await askQuestion("Summarize the refund policy.");
  await expect(page.getByTestId("demo-banner")).toContainText("1 of 3 questions left");
  await askQuestion("Who pays for return shipping?");
  await expect(page.getByTestId("demo-banner")).toContainText("0 of 3 questions left");
  await expect(page.getByTestId("answer")).toHaveCount(3);

  await page.getByLabel("Your question").fill("One more question?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const modal = page.getByTestId("demo-limit-modal");
  await expect(modal).toBeVisible();
  await expect(modal.getByRole("heading")).toHaveText("Create a free account to continue");
  await expect(modal).toContainText("You've used all 3 demo questions.");
  await shot(page, "demo-limit-modal-dark", false);
});

test("light theme renders the chat and the modal too", async () => {
  await page.getByTestId("demo-limit-modal").getByRole("button", { name: "Not now" }).click();
  await page.getByTestId("theme-toggle").first().click();
  await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
  await page.getByTestId("answer").first().getByRole("button", { name: "Citation 1" }).click();
  await shot(page, "ask-citations-light");
  await page.getByRole("button", { name: "Create free account" }).click();
  await expect(page.getByTestId("demo-limit-modal")).toBeVisible();
  await shot(page, "demo-limit-modal-light", false);
  await page.getByRole("button", { name: "Not now" }).click();
});

test("mobile: bottom navigation and demo banner", async ({ browser }) => {
  const mobile = await newContextPage(browser, {
    viewport: MOBILE,
    isMobile: true,
    hasTouch: true,
    storageState: await page.context().storageState(),
  });
  for (const theme of ["dark", "light"] as const) {
    await presetTheme(mobile, theme);
    await mobile.goto("/ask");
    await expect(mobile.getByRole("navigation", { name: "Main" })).toBeVisible();
    await expect(mobile.getByTestId("demo-banner")).toContainText("0 of 3 questions left");
    const overflow = await mobile.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    await shot(mobile, `ask-mobile-${theme}`, false);
    await mobile.goto("/dashboard");
    await expect(mobile.getByTestId("count-total")).toHaveText("1");
    await shot(mobile, `dashboard-mobile-${theme}`, false);
  }
  await mobile.context().close();
});

test("convert the demo into a free account; the document is kept", async () => {
  const email = `demo-convert-${Date.now().toString(36)}@example.com`;
  await page.getByRole("button", { name: "Create free account" }).click();
  const modal = page.getByTestId("demo-limit-modal");
  await modal.getByLabel("Email").fill(email);
  await modal.getByLabel("Password").fill("e2e-password-1234");
  await modal.getByTestId("demo-convert-submit").click();
  await expect(page.getByTestId("toast").filter({ hasText: "Account created" })).toBeVisible();
  await expect(page.getByTestId("demo-banner")).toHaveCount(0);
  await expect(page.getByTestId("user-email")).toHaveText(email);
  await page.goto("/dashboard");
  await expect(page.getByTestId("count-completed")).toHaveText("1");
  await expect(page.getByTestId("recent-activity")).toContainText("Demo converted to a free account");
  await page.goto("/settings");
  await page.getByTestId("theme-toggle").first().click(); // back to dark
  await page.goto("/dashboard");
  await shot(page, "dashboard-desktop-dark");
  await page.getByTestId("theme-toggle").first().click();
  await shot(page, "dashboard-desktop-light");
  // Regular account: asking works again past the demo limit.
  await page.goto(`/ask?document=${documentId}`);
  await askQuestion("What is the refund window?");
  await expect(page.getByTestId("answer").last()).toContainText("According to the document");
  // Expected API refusals (403/429) are logged by the browser as failed resources; nothing else.
  expect(errors.filter((e) => !/Failed to load resource: the server responded with a status of 40[39]/.test(e))).toEqual([]);
  await page.context().close();
});
