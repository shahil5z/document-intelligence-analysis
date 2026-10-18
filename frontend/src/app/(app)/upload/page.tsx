import type { Metadata } from "next";

import { Uploader } from "./Uploader";

export const metadata: Metadata = { title: "Upload" };

export default function Page() {
  return <Uploader />;
}
