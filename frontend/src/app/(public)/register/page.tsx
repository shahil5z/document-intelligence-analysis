import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "@/components/AuthForm";
import { LoadingRows } from "@/components/ui";

export const metadata: Metadata = { title: "Create account" };

export default function Page() {
  return (
    <Suspense fallback={<LoadingRows rows={3} />}>
      <AuthForm mode="register" />
    </Suspense>
  );
}
