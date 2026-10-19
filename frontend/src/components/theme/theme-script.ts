/** localStorage key holding "light" or "dark". Missing/invalid = dark (the default). */
export const THEME_STORAGE_KEY = "dia-theme";
export type Theme = "light" | "dark";
export const DEFAULT_THEME: Theme = "dark";

/**
 * Runs in <head> before first paint, so the stored theme is applied without a flash. The
 * server always renders class="dark" (the default); <html suppressHydrationWarning>
 * tolerates the script changing it to light before React hydrates.
 */
export const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY,
)});if(t!=="light"&&t!=="dark")t=${JSON.stringify(DEFAULT_THEME)};var d=document.documentElement;d.classList.toggle("dark",t==="dark");d.style.colorScheme=t;d.dataset.theme=t}catch(e){}})();`;
