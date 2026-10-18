import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingRows } from "@/components/ui";

import { SearchView } from "./SearchView";

export const metadata: Metadata = { title: "Search" };

export default function Page() {
  return (
    <Suspense fallback={<LoadingRows rows={4} label="Loading search" />}>
      <SearchView />
    </Suspense>
  );
}
