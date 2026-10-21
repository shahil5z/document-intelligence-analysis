import { expect, test, type Page } from "@playwright/test";

// Suggested questions in the Ask panel. The stub LLM stack never generates them, so the
// document API responses are mocked in the browser (no LLM call is made).
const DOC_ID = "11111111-2222-4333-8444-555555555555";
const GENERATED = [
  "How often are the kiosks inspected?",
  "Who receives fault reports?",
  "When are meeting-room displays replaced?",
];

function doc(status: string, suggested: string[] | null) {
  return {
    id: DOC_ID,
    original_filename: "maintenance-guide.pdf",
    content_type: "application/pdf",
    file_size: 2300,
    checksum_sha256: "0".repeat(64),
    status,
    created_at: "2026-10-20T10:00:00Z",
    updated_at: "2026-10-20T10:00:00Z",
    suggested_questions: suggested,
  };
}

async function signUp(page: Page) {
  await page.goto("/register");
  await page.getByLabel("Email").fill(`suggest-${Date.now().toString(36)}@example.com`);
  await page.getByLabel("Password").fill("e2e-password-1234");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
}

test("ask panel shows generated questions, a pending state and the static fallback", async ({ page }) => {
  await signUp(page);

  // 1. No documents with suggestions: static starters.
  await page.goto("/ask");
  await expect(page.getByTestId("suggestions")).toHaveAttribute("data-generated", "false");
  await expect(page.getByTestId("starter-question").first()).toHaveText("Summarize the key points.");

  // 2. "Ask across all": questions from the most recent completed document.
  await page.route("**/api/proxy/documents?*", (route) =>
    route.fulfill({ json: { total: 1, page: 1, page_size: 10, items: [doc("completed", GENERATED)] } }),
  );
  await page.goto("/ask");
  await expect(page.getByTestId("suggestions")).toHaveAttribute("data-generated", "true");
  await expect(page.getByTestId("starter-question")).toHaveText(GENERATED);
  await page.unroute("**/api/proxy/documents?*");

  // 3. Selected document still processing: pending hint, then its questions.
  let processing = true;
  await page.route(`**/api/proxy/documents/${DOC_ID}`, (route) =>
    route.fulfill({ json: processing ? doc("processing", null) : doc("completed", GENERATED) }),
  );
  await page.goto(`/ask?document=${DOC_ID}`);
  await expect(page.getByTestId("suggestions-pending")).toBeVisible();
  processing = false;
  await expect(page.getByTestId("starter-question")).toHaveText(GENERATED, { timeout: 10_000 });
  await expect(page.getByText("Suggested from")).toContainText("maintenance-guide.pdf");

  // 4. A question link from the document page pre-fills the input (nothing is sent).
  await page.goto(`/ask?document=${DOC_ID}&q=${encodeURIComponent(GENERATED[1])}`);
  await expect(page.getByLabel("Your question")).toHaveValue(GENERATED[1]);
});
