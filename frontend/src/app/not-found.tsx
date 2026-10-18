import Link from "next/link";

export default function NotFound() {
  return (
    <main id="main" className="mx-auto flex min-h-[60vh] max-w-md flex-col items-center justify-center px-4 text-center">
      <p className="text-sm font-semibold text-brand-600">404</p>
      <h1 className="mt-2 text-2xl font-semibold">Page not found</h1>
      <p className="mt-2 text-sm text-slate-600">The page you were looking for does not exist.</p>
      <Link href="/" className="mt-6 text-sm font-medium text-brand-700 hover:underline">
        Go to the home page
      </Link>
    </main>
  );
}
