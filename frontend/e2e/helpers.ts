import path from "node:path";

import type { Browser, BrowserContextOptions, Page } from "@playwright/test";

// Screenshots land in frontend/e2e-screenshots/ (git-ignored); docs/screenshots/ holds a
// curated, hand-picked subset. Set E2E_SCREENSHOT_DIR to write elsewhere.
export const SCREENSHOTS = process.env.E2E_SCREENSHOT_DIR ?? path.resolve(__dirname, "../e2e-screenshots");
export const FIXTURES = path.resolve(__dirname, "fixtures");

export const DESKTOP = { width: 1366, height: 900 };
export const MOBILE = { width: 375, height: 812 };

export async function shot(page: Page, name: string, fullPage = true) {
  await page.screenshot({ path: path.join(SCREENSHOTS, `${name}.png`), fullPage, animations: "disabled" });
}

/** Console errors and uncaught page errors (hydration mismatches end up here too). */
export function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

export async function newContextPage(browser: Browser, options: BrowserContextOptions = {}): Promise<Page> {
  const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: DESKTOP, ...options });
  return context.newPage();
}

/** Set the persisted theme before any page script runs (same key the app uses). */
export async function presetTheme(page: Page, theme: "light" | "dark") {
  await page.addInitScript((value) => {
    try {
      window.localStorage.setItem("dia-theme", value);
    } catch {
      /* ignore */
    }
  }, theme);
}
