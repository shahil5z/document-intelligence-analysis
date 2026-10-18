import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingRows } from "@/components/ui";

import { AskView } from "./AskView";

export const metadata: Metadata = { title: "Ask AI" };

export default function Page() {
  return (
    <Suspense fallback={<LoadingRows rows={4} label="Loading" />}>
      <AskView />
    </Suspense>
  );
}
