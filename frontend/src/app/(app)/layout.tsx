import { Suspense } from "react";

import { AppShell } from "@/components/AppShell";
import { SessionProvider } from "@/components/SessionProvider";
import { LoadingRows } from "@/components/ui";

// The app pages depend on the signed-in user and the URL, so they render on the client;
// the static shell shows a skeleton until then.
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-6xl px-4 py-8">
          <LoadingRows rows={6} label="Loading" />
        </div>
      }
    >
      <SessionProvider>
        <AppShell>{children}</AppShell>
      </SessionProvider>
    </Suspense>
  );
}
