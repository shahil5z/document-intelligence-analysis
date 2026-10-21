import type { Metadata } from "next";

import { LegalPage, Placeholder } from "@/components/LegalPage";
import { PRODUCT_NAME } from "@/lib/brand";

export const metadata: Metadata = { title: "Impressum" };

export default function ImpressumPage() {
  return (
    <LegalPage title="Impressum" updated="2026-10-19">
      <p>
        Information according to § 5 ECG (Austrian E-Commerce Act), § 25 MedienG (Austrian
        Media Act) and § 14 UGB where applicable.
      </p>
      <h2>Operator / media owner</h2>
      <p>
        <Placeholder>Full name</Placeholder>
        <br />
        <Placeholder>Street and number</Placeholder>
        <br />
        <Placeholder>Postal code, city</Placeholder>
        <br />
        Austria
      </p>
      <h2>Contact</h2>
      <p>
        E-mail: <Placeholder>contact e-mail address</Placeholder>
        <br />
        Phone (optional): <Placeholder>phone number</Placeholder>
      </p>
      <h2>Purpose of this website</h2>
      <p>
        {PRODUCT_NAME} is a non-commercial software project that demonstrates document
        search and question answering with cited sources. <Placeholder>adjust if the site is
        operated commercially, and add company register / VAT details if applicable</Placeholder>
      </p>
      <h2>Basic direction (§ 25 Abs 4 MedienG)</h2>
      <p>Presentation of a software project and its technical background.</p>
      <h2>Liability for content and links</h2>
      <p>
        The content was prepared with care, but no guarantee is given for completeness or
        accuracy. AI-generated answers can be wrong; check the cited passages. External
        links are the responsibility of their operators.
      </p>
      <h2>Online dispute resolution</h2>
      <p>
        EU platform for online dispute resolution:{" "}
        <a className="text-link underline" href="https://ec.europa.eu/consumers/odr" rel="noopener noreferrer">
          ec.europa.eu/consumers/odr
        </a>
        . <Placeholder>remove if no consumer contracts are concluded</Placeholder>
      </p>
    </LegalPage>
  );
}
