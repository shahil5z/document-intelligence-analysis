import { expect, test } from "@playwright/test";

import { DESKTOP, MOBILE, newContextPage, presetTheme, shot, watchConsole } from "./helpers";

// Dark is the default, the toggle persists across reloads, the class is set before
// first paint (inline head script), and public pages log no console/hydration errors.

test("default theme is dark and the toggle persists across reload", async ({ browser }) => {
  const page = await newContextPage(browser);
  const errors = watchConsole(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  // Read at DOMContentLoaded: the class must already be there (no light flash).
  expect(await page.evaluate(() => document.documentElement.classList.contains("dark"))).toBe(true);
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toContain("dark");
  const toggle = page.getByTestId("theme-toggle").first();
  await expect(toggle).toHaveAttribute("data-theme-current", "dark");
  await expect(toggle).toHaveAccessibleName("Switch to light mode");

  await toggle.click();
  await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
  await expect(toggle).toHaveAttribute("data-theme-current", "light");
  expect(await page.evaluate(() => localStorage.getItem("dia-theme"))).toBe("light");

  await page.reload({ waitUntil: "domcontentloaded" });
  expect(await page.evaluate(() => document.documentElement.classList.contains("dark"))).toBe(false);
  await expect(page.getByTestId("theme-toggle").first()).toHaveAttribute("data-theme-current", "light");

  // The choice carries over to other pages (auth pages have the toggle too).
  await page.goto("/login");
  await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
  await page.getByTestId("theme-toggle").first().click();
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  expect(errors).toEqual([]);
  await page.context().close();
});

for (const theme of ["dark", "light"] as const) {
  for (const [device, viewport] of [["desktop", DESKTOP], ["mobile", MOBILE]] as const) {
    test(`public pages, ${theme}, ${device}: no console errors, screenshots`, async ({ browser }) => {
      const page = await newContextPage(browser, {
        viewport,
        ...(device === "mobile" ? { isMobile: true, hasTouch: true } : {}),
      });
      await presetTheme(page, theme);
      const errors = watchConsole(page);
      for (const [route, name] of [
        ["/", "landing"],
        ["/login", "login"],
        ["/register", "register"],
        ["/impressum", "impressum"],
        ["/privacy", "privacy"],
      ] as const) {
        await page.goto(route);
        await expect(page.locator("html")).toHaveClass(theme === "dark" ? /\bdark\b/ : /^(?!.*\bdark\b)/);
        await expect(page.getByRole("img", { name: "Document Intelligence & Analysis" }).first()).toBeVisible();
        // No horizontal overflow down to 375px.
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(overflow, `${route} overflows horizontally`).toBeLessThanOrEqual(0);
        if (["landing", "login", "impressum"].includes(name)) await shot(page, `${name}-${device}-${theme}`);
      }
      await expect(page).toHaveTitle(/Document Intelligence & Analysis/);
      expect(errors).toEqual([]);
      await page.context().close();
    });
  }
}
