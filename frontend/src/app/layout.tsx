import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata, Viewport } from "next";

import { ToastProvider } from "@/components/Toast";
import { THEME_INIT_SCRIPT } from "@/components/theme/theme-script";
import { PRODUCT_NAME, PRODUCT_TAGLINE } from "@/lib/brand";

import "./globals.css";

function siteUrl(): URL {
  const explicit = process.env.NEXT_PUBLIC_SITE_URL;
  if (explicit) return new URL(explicit);
  const vercel = process.env.VERCEL_PROJECT_PRODUCTION_URL;
  return new URL(vercel ? `https://${vercel}` : "http://localhost:3000");
}

export const metadata: Metadata = {
  metadataBase: siteUrl(),
  applicationName: PRODUCT_NAME,
  title: { default: PRODUCT_NAME, template: `%s · ${PRODUCT_NAME}` },
  description: PRODUCT_TAGLINE,
  icons: {
    icon: [{ url: "/favicon.ico", sizes: "16x16 32x32 48x48" }],
    apple: [{ url: "/brand/apple-touch-icon.png", sizes: "180x180" }],
  },
  openGraph: {
    type: "website",
    siteName: PRODUCT_NAME,
    title: PRODUCT_NAME,
    description: PRODUCT_TAGLINE,
    images: [{ url: "/brand/og-image.png", width: 1200, height: 630, alt: PRODUCT_NAME }],
  },
  twitter: {
    card: "summary_large_image",
    title: PRODUCT_NAME,
    description: PRODUCT_TAGLINE,
    images: ["/brand/og-image.png"],
  },
  // The app has its own dark mode; ask the Dark Reader extension not to restyle it.
  other: { "darkreader-lock": "" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "dark light",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0b1020" },
    { media: "(prefers-color-scheme: light)", color: "#f7f8fb" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // Dark is the default theme. suppressHydrationWarning: the inline script may switch
    // the class to "light" before hydration, and extensions (e.g. Dark Reader) add
    // attributes to <html>/<body>; neither is a real mismatch.
    <html
      lang="en"
      className={`dark ${GeistSans.variable} ${GeistMono.variable}`}
      style={{ colorScheme: "dark" }}
      data-theme="dark"
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-screen font-sans" suppressHydrationWarning>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-surface focus:px-4 focus:py-2 focus:text-fg focus:shadow"
        >
          Skip to content
        </a>
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
