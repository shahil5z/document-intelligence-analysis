import type { Metadata } from "next";

import { LegalPage, Placeholder } from "@/components/LegalPage";
import { PRODUCT_NAME } from "@/lib/brand";

export const metadata: Metadata = { title: "Privacy policy" };

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy policy" updated="2026-10-19">
      <p>
        This policy explains which personal data {PRODUCT_NAME} processes, why, and what
        rights you have under the EU General Data Protection Regulation (GDPR) and the
        Austrian Data Protection Act (DSG).
      </p>
      <h2>Controller</h2>
      <p>
        <Placeholder>Full name</Placeholder>, <Placeholder>postal address</Placeholder>, e-mail{" "}
        <Placeholder>contact e-mail address</Placeholder>. No data protection officer is
        appointed (not required). <Placeholder>adjust if one is appointed</Placeholder>
      </p>
      <h2>What is processed</h2>
      <ul>
        <li>
          <strong>Account data</strong>: e-mail address and a password hash (Argon2), to
          provide your account (Art. 6(1)(b) GDPR).
        </li>
        <li>
          <strong>Documents you upload</strong> and the text passages and embeddings derived
          from them, to provide search and answers (Art. 6(1)(b)). Only you can access them.
        </li>
        <li>
          <strong>Questions</strong> you ask. To answer, the question and the most relevant
          passages of your documents are sent to the language-model provider{" "}
          <Placeholder>OpenAI, L.L.C. / other provider; data processing agreement and
          transfer basis (e.g. EU-US Data Privacy Framework or SCCs)</Placeholder>. After
          each upload, the beginning of the document text is also sent to the same provider
          once to suggest questions.
        </li>
        <li>
          <strong>Technical logs</strong>: request time, path, status, a request id and
          your IP address in hashed form for rate limiting, for security and abuse
          prevention (Art. 6(1)(f), legitimate interest). Question and document text are not
          logged. Retention: <Placeholder>e.g. 14 days</Placeholder>.
        </li>
        <li>
          <strong>Demo sessions</strong>: demo accounts and their documents are deleted
          automatically 24 hours after creation.
        </li>
      </ul>
      <h2>Cookies and tracking</h2>
      <p>
        One strictly necessary, HttpOnly session cookie (<code>dip_session</code>) keeps you
        signed in; it is removed when you sign out or it expires. Your light/dark theme
        choice is stored in your browser&apos;s local storage. There are no analytics,
        advertising or third-party tracking cookies, so no consent banner is needed.
      </p>
      <h2>Hosting and processors</h2>
      <p>
        Frontend: <Placeholder>e.g. Vercel Inc.</Placeholder>. API, database and file
        storage: <Placeholder>e.g. Oracle Cloud Infrastructure, region</Placeholder>.
        Language model: <Placeholder>provider</Placeholder>.
      </p>
      <h2>Retention and deletion</h2>
      <p>
        Documents are kept until you delete them; deleting a document removes the file, its
        passages and embeddings. To delete your account, contact{" "}
        <Placeholder>contact e-mail address</Placeholder>.
      </p>
      <h2>Your rights</h2>
      <p>
        You have the right of access, rectification, erasure, restriction, data
        portability and objection (Art. 15-21 GDPR). You may lodge a complaint with the
        Austrian Data Protection Authority (Datenschutzbehörde, Barichgasse 40-42, 1030
        Vienna, dsb.gv.at).
      </p>
    </LegalPage>
  );
}
