import Link from "next/link";
import { Logo } from "@/components/Logo";

export const metadata = {
  title: "Terms & Disclaimer — Schedule Narrative Generator",
};

// Public legal page (not wrapped in SubscriptionGate, so reachable signed-out).
// NOTE: this is a plain-language starting draft, not attorney-reviewed. Company
// name / governing-law state are placeholders to finalize once the LLC exists.
export default function TermsPage() {
  return (
    <div className="min-h-screen">
      <div className="mx-auto max-w-2xl px-6 py-16">
        <div className="flex items-center justify-between border-b border-rule pb-5 mb-10">
          <Link href="/"><Logo markSize={34} /></Link>
          <Link href="/" className="text-sm text-ink-muted hover:text-oxide transition-colors">
            Back to app
          </Link>
        </div>

        <h1 className="text-2xl font-semibold tracking-tight mb-2">Terms of Use &amp; Disclaimer</h1>
        <p className="text-xs text-ink-muted mb-10">Last updated: July 12, 2026</p>

        <div className="space-y-8 text-sm leading-relaxed text-ink">
          <section>
            <p>
              These Terms of Use and Disclaimer (&ldquo;Terms&rdquo;) govern your access to and use of
              Schedule Narrative Generator (the &ldquo;Service,&rdquo; &ldquo;we,&rdquo; &ldquo;us&rdquo;).
              By accessing or using the Service, including uploading a schedule or generating a narrative,
              you agree to these Terms. If you do not agree, do not use the Service.
            </p>
          </section>

          <section>
            <h2 className="font-semibold mb-2">1. What the Service does</h2>
            <p>
              The Service produces automated, plain-language written summaries (&ldquo;narratives&rdquo;)
              generated from Primavera P6 schedule files that you upload. It reads and describes the data in
              the file you provide. It is a drafting aid. It does not create, model, calculate, or validate
              a schedule, and it does not run a full critical path method (CPM) analysis.
            </p>
          </section>

          <section>
            <h2 className="font-semibold mb-2">2. Not professional advice</h2>
            <p>
              The narratives are not, and must not be relied upon as, professional advice of any kind &mdash;
              including engineering, architectural, construction-management, scheduling, project-controls,
              legal, financial, or accounting advice. The Service is not a substitute for review by a
              qualified professional. Any decision you make is your own responsibility.
            </p>
          </section>

          <section>
            <h2 className="font-semibold mb-2">3. Accuracy and your responsibility to verify</h2>
            <p>
              Narratives are generated automatically from the file you provide and may contain errors,
              omissions, or approximations. Certain values (for example, float and critical-path status) are
              derived or approximated from schedule dates and fields and may differ from the values shown in
              Primavera P6 or from a formal schedule analysis. You are solely responsible for reviewing,
              verifying, and validating any narrative &mdash; against the source schedule and, where
              appropriate, with a qualified professional &mdash; before relying on it, acting on it,
              distributing it, or using it for any purpose.
            </p>
          </section>

          <section>
            <h2 className="font-semibold mb-2">4. No use as a basis for claims or disputes</h2>
            <p>
              Narratives must not be used as the sole or primary basis for any contractual claim, delay or
              disruption claim, notice, dispute, litigation, arbitration, or other legal, contractual, or
              financial decision or proceeding. Any such use requires independent verification and
              professional judgment. You assume all risk arising from any use of a narrative in connection
              with a claim, dispute, or proceeding.
            </p>
          </section>

          <section>
            <h2 className="font-semibold mb-2">5. Service provided &ldquo;as is&rdquo;</h2>
            <p>
              The Service and all narratives are provided &ldquo;as is&rdquo; and &ldquo;as available,&rdquo;
              without warranties of any kind, whether express, implied, or statutory, including any implied
              warranties of merchantability, fitness for a particular purpose, accuracy, reliability, title,
              or non-infringement. We do not warrant that the Service will be uninterrupted, error-free, or
              that any narrative will be accurate or complete.
            </p>
          </section>

          <section>
            <h2 className="font-semibold mb-2">6. Limitation of liability</h2>
            <p>
              To the maximum extent permitted by law, in no event will the Service, its owners, operators,
              or affiliates be liable for any indirect, incidental, special, consequential, exemplary, or
              punitive damages, or for any loss of profits, revenue, data, goodwill, or business, or for any
              damages arising from any claim, dispute, decision, or proceeding, arising out of or relating to
              your use of the Service or any narrative, whether based in contract, tort, negligence, strict
              liability, or otherwise, even if advised of the possibility of such damages. To the maximum
              extent permitted by law, our total aggregate liability for all claims relating to the Service
              will not exceed the greater of the total fees you paid to us in the twelve (12) months
              preceding the event giving rise to the claim, or fifty U.S. dollars (US$50).
            </p>
          </section>

          <section>
            <h2 className="font-semibold mb-2">7. Indemnification</h2>
            <p>
              You agree to indemnify, defend, and hold harmless the Service and its owners, operators, and
              affiliates from and against any claims, demands, damages, liabilities, losses, costs, and
              expenses (including reasonable attorneys&rsquo; fees) arising out of or related to your use of
              the Service or any narrative, the files or data you upload, your use of any output in any
              claim, dispute, or proceeding, or your violation of these Terms or of any applicable law or
              third-party right.
            </p>
          </section>

          <section>
            <h2 className="font-semibold mb-2">8. Your data and files</h2>
            <p>
              You retain ownership of the files and data you upload. You represent and warrant that you have
              the right to upload and process that data and that doing so does not violate any agreement,
              confidentiality obligation, or law. You are responsible for the content of the files you
              provide.
            </p>
          </section>

          <section>
            <h2 className="font-semibold mb-2">9. Service limits</h2>
            <p>
              The Service has technical limits, including a maximum upload file size of 50 MB. Files larger
              than this limit will not be processed; you will be told the limit and your file&rsquo;s size
              before any upload begins. These limits may change.
            </p>
          </section>

          <section>
            <h2 className="font-semibold mb-2">10. Changes to these Terms</h2>
            <p>
              We may update these Terms from time to time. Changes are effective when posted. Your continued
              use of the Service after changes are posted constitutes acceptance of the updated Terms.
            </p>
          </section>

          <section>
            <h2 className="font-semibold mb-2">11. Governing law</h2>
            <p>
              These Terms are governed by the laws of the State of [STATE], without regard to its
              conflict-of-laws rules. Any dispute will be subject to the exclusive jurisdiction of the state
              and federal courts located in [COUNTY/STATE].
            </p>
          </section>

          <section>
            <h2 className="font-semibold mb-2">12. Contact</h2>
            <p>
              Questions about these Terms:{" "}
              <a href="mailto:feedback@schedulenarrative.com" className="text-oxide hover:brightness-110">
                feedback@schedulenarrative.com
              </a>
              .
            </p>
          </section>
        </div>

        <footer className="mt-16 pt-6 border-t border-rule text-xs text-ink-muted">
          <Link href="/" className="hover:text-oxide transition-colors">Back to Schedule Narrative Generator</Link>
        </footer>
      </div>
    </div>
  );
}
