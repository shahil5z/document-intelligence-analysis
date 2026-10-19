import Link from "next/link";

import { Wordmark } from "@/components/Logo";

export default function NotFound() {
  return (
    <main id="main" className="mx-auto flex min-h-[70vh] max-w-md flex-col items-center justify-center px-4 text-center">
      <Link href="/" aria-label="Home" className="mb-10">
        <Wordmark />
      </Link>
      <p className="text-sm font-semibold text-link">404</p>
      <h1 className="mt-2 text-2xl font-semibold text-fg">Page not found</h1>
      <p className="mt-2 text-sm text-muted">The page you were looking for does not exist.</p>
      <Link href="/" className="mt-6 text-sm font-medium text-link hover:underline">
        Go to the home page
      </Link>
    </main>
  );
}
