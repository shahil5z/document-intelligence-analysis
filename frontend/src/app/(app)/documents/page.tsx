import type { Metadata } from "next";

import { DocumentsList } from "./DocumentsList";

export const metadata: Metadata = { title: "Documents" };

export default function Page() {
  return <DocumentsList />;
}
