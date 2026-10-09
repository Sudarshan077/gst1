/**
 * Task 9.4 gate — Playwright: ITC reconciliation dashboard
 * (PHASE9_QA_SWEEP_FIXES.md §3.9.4, FRONTEND_SPECIFICATION.md §3.5).
 * Backend (8084) + frontend dev server (9094) must be running; the backend
 * needs PG:5436 + Redis:6380 (bootstrap_stack.py).
 *
 * done_when:
 *  - a seeded period (4 confirmed PURCHASE invoices + an imported GSTR-2B
 *    statement) shows the 2B import status block, and after reconcile the
 *    books-vs-2B table renders one row per verdict with the status badge:
 *    MATCHED / PROBABLE / UNMATCHED / MISSING_IN_2B / MISSING_IN_BOOKS;
 *  - the status filter narrows the table; the ITC summary prefill card shows
 *    both sides' paise totals; the chase-supplier list carries the
 *    MISSING_IN_2B row;
 *  - the screen is reachable BY CLICKING THE NAV from /app (nav-link-itc), and
 *    ShellNav.tsx statically links the /app/itc route (reachability audit).
 *
 * Uses the existing backend endpoints only. Purchases are seeded through the
 * shipped dev-extraction pipeline: upload → dev extract → PUT draft (supplier
 * = the synthetic vendor, buyer = the registration, invoice_no = a known
 * fixture value) → confirm, which is what makes the direction PURCHASE and
 * gives the reconciliation engine stable invoice numbers to match on.
 * Synthetic fixtures only; GSTINs are checksum-valid by construction
 * (makeGstin, same mod-36 rule as lib/validation/gstin.ts).
 */
import { expect, test, Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const BACKEND = "http://127.0.0.1:8084";
const FP = "092026";

/**
 * Fixture invoice numbers, chosen so the engine's fuzzy (SequenceMatcher
 * ratio > 0.8) path is unambiguous: only PUR-PROBABLE-BB vs PUR-PROBABL-BB
 * clears the threshold; every other cross pair stays under it.
 */
const BOOKS_MATCHED = "PUR-MATCH-AA";
const BOOKS_PROBABLE = "PUR-PROBABL-BB"; // books has the typo…
const TWO_B_PROBABLE = "PUR-PROBABLE-BB"; // …the 2B statement spells it right
const BOOKS_UNMATCHED = "PUR-UNMATC-CC";
const BOOKS_MISSING_2B = "PUR-BOOKS-DD";
const TWO_B_ONLY = "S2B-ONLY-EE";

function uniqueEmail(): string {
  return `test_${Date.now()}_${Math.random().toString(36).slice(2, 8)}@example.com`;
}

/** Mod-36 checksum-valid synthetic GSTIN (same rule as lib/validation/gstin.ts). */
function makeGstin(): string {
  const state = "27";
  const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  const digits = "0123456789";
  const pan =
    Array.from({ length: 5 }, () => letters[Math.floor(Math.random() * 26)]).join("") +
    Array.from({ length: 4 }, () => digits[Math.floor(Math.random() * 10)]).join("") +
    letters[Math.floor(Math.random() * 26)];
  const first14 = `${state}${pan}1Z`;
  const charset = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  const weights = [1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2];
  let total = 0;
  for (let i = 0; i < 14; i += 1) {
    const prod = charset.indexOf(first14[i]) * weights[i];
    total += Math.floor(prod / 36) + (prod % 36);
  }
  const check = charset[(36 - (total % 36)) % 36];
  return `${first14}${check}`;
}

/** Distinct bytes per variant: the backend dedupes documents by sha256. */
function minimalPdf(variant: string): Buffer {
  return Buffer.from(
    `%PDF-1.4\n% itc-${variant}\n` +
      "1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n" +
      "2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n" +
      "3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/MediaBox [0 0 612 792]\n>>\nendobj\n" +
      "xref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n" +
      "0000000058 00000 n\n0000000115 00000 n\n" +
      "trailer\n<<\n/Size 4\n/Root 1 0 R\n>>\nstartxref\n196\n%%EOF",
  );
}

async function registerApi(email: string): Promise<string> {
  const otpRes = await fetch(`${BACKEND}/api/v1/auth/otp/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier: email, purpose: "REGISTER" }),
  });
  const otpBody = (await otpRes.json()) as {
    success: boolean;
    data?: { dev_otp?: string };
  };
  expect(otpBody.success).toBe(true);
  const verifyRes = await fetch(`${BACKEND}/api/v1/auth/otp/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier: email, otp: otpBody.data!.dev_otp! }),
  });
  expect(verifyRes.status).toBe(200);
  const body = (await verifyRes.json()) as { data: { access_token: string } };
  return body.data.access_token;
}

async function createGstAccount(token: string, gstin: string): Promise<void> {
  const res = await fetch(`${BACKEND}/api/v1/gst-accounts`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ gstin, legal_name: `ITC Dash Co ${Date.now()}` }),
  });
  expect([200, 201, 409]).toContain(res.status);
}

/**
 * Seed ONE confirmed purchase invoice through the shipped pipeline:
 *   upload → dev extract → PUT draft (supplier = vendor, buyer = the
 *   registration ⇒ direction PURCHASE, invoice_no = the fixture value) →
 *   confirm.
 */
async function seedPurchase(
  token: string,
  gstin: string,
  supplierGstin: string,
  invoiceNo: string,
  variant: string,
): Promise<void> {
  const form = new FormData();
  form.append("capture_source", "PDF_SCAN");
  form.append(
    "files",
    new Blob([new Uint8Array(minimalPdf(variant))], { type: "application/pdf" }),
    `purchase-${variant}.pdf`,
  );
  const upRes = await fetch(
    `${BACKEND}/api/v1/gst-accounts/${gstin}/months/${FP}/documents`,
    { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: form },
  );
  expect(upRes.status).toBe(200);
  const docId = ((await upRes.json()) as { data: { id: string } }).data.id;

  const extractRes = await fetch(`${BACKEND}/api/v1/documents/${docId}/extract`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
  });
  expect(extractRes.status).toBe(200);

  const putRes = await fetch(`${BACKEND}/api/v1/documents/${docId}/draft`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      supplier_gstin: supplierGstin,
      buyer_gstin: gstin,
      invoice_no: invoiceNo,
    }),
  });
  expect(putRes.status).toBe(200);

  const confirmRes = await fetch(`${BACKEND}/api/v1/documents/${docId}/confirm`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
  });
  expect(confirmRes.status).toBe(200);
}

/** Seed the 4 purchase invoices and import the matching GSTR-2B statement. */
async function seedReconciledPeriod(token: string, gstin: string): Promise<void> {
  const supplier = makeGstin(); // same state (27) ⇒ INTRA, cgst/sgst split
  await createGstAccount(token, gstin);

  await seedPurchase(token, gstin, supplier, BOOKS_MATCHED, "matched");
  await seedPurchase(token, gstin, supplier, BOOKS_PROBABLE, "probable");
  await seedPurchase(token, gstin, supplier, BOOKS_UNMATCHED, "unmatched");
  await seedPurchase(token, gstin, supplier, BOOKS_MISSING_2B, "books-only");

  // The seed draft is always taxable 100000 + cgst 9000 + sgst 9000 ⇒ the
  // confirmed invoice total is 118000 paise. The engine compares a 2B entry's
  // taxable figure against the books invoice total.
  const importRes = await fetch(
    `${BACKEND}/api/v1/gst-accounts/${gstin}/months/${FP}/gstr2b/import`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        payload: {
          entries: [
            {
              supplier_gstin: supplier,
              invoice_no: BOOKS_MATCHED, // exact invoice no + amount ⇒ MATCHED
              invoice_date: "2026-09-10",
              taxable_value_minor: 118000,
              cgst_minor: 9000,
              sgst_minor: 9000,
              doc_type: "INV",
            },
            {
              supplier_gstin: supplier,
              invoice_no: TWO_B_PROBABLE, // typo of the books number ⇒ PROBABLE
              invoice_date: "2026-09-11",
              taxable_value_minor: 118000,
              cgst_minor: 9000,
              sgst_minor: 9000,
              doc_type: "INV",
            },
            {
              supplier_gstin: supplier,
              invoice_no: BOOKS_UNMATCHED, // same no, amount far off ⇒ UNMATCHED
              invoice_date: "2026-09-12",
              taxable_value_minor: 99999,
              cgst_minor: 4500,
              sgst_minor: 4500,
              doc_type: "INV",
            },
            {
              supplier_gstin: supplier,
              invoice_no: TWO_B_ONLY, // absent from books ⇒ MISSING_IN_BOOKS
              invoice_date: "2026-09-13",
              taxable_value_minor: 30000,
              cgst_minor: 2700,
              sgst_minor: 2700,
              doc_type: "INV",
            },
          ],
        },
      }),
    },
  );
  expect(importRes.status).toBe(200);
}

async function loginViaUi(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("login-identifier").fill(email);
  await page.getByTestId("login-request-otp").click();
  const banner = page.getByTestId("dev-otp");
  await expect(banner).toBeVisible({ timeout: 15_000 });
  const match = (await banner.textContent())?.match(/dev code:\s*(\d{6})/);
  expect(match).toBeTruthy();
  await page.getByTestId("login-otp").fill(match![1]);
  await page.getByTestId("login-verify").click();
  await expect(page).toHaveURL(/\/app$/, { timeout: 10_000 });
}

test.describe("9.4 ITC reconciliation dashboard", () => {
  test("seeded period -> badges per status; nav click reaches /app/itc from /app", async ({
    page,
  }) => {
    const email = uniqueEmail();
    const token = await registerApi(email);
    const gstin = makeGstin();
    await seedReconciledPeriod(token, gstin);

    await loginViaUi(page, email);

    // --- Reachability: click the nav link from the dashboard. ---------------
    await page.goto("/app");
    await expect(page.getByTestId("shell-nav-links")).toBeVisible();
    await page.getByTestId("nav-link-itc").click();
    await expect(page).toHaveURL(new RegExp(`/app/itc/${gstin}/\\d{6}$`), {
      timeout: 15_000,
    });

    await expect(page.getByTestId("itc-page")).toBeVisible({ timeout: 15_000 });

    // 1. 2B import status block.
    await expect(page.getByTestId("itc-statement-status")).toBeVisible();
    await expect(page.getByTestId("itc-statement-entries")).toHaveText("4");
    await expect(page.getByTestId("itc-statement-empty")).toHaveCount(0);

    // 2. Reconcile through the real engine (a seeded period has no
    // reconciliation rows until this runs), then the table fills in.
    await page.getByTestId("itc-reconcile").click();
    await expect(page.getByTestId("itc-table")).toBeVisible({ timeout: 20_000 });

    const badges = page.getByTestId("itc-badge");
    await expect(badges).toHaveCount(5, { timeout: 20_000 });
    expect((await badges.allTextContents()).sort()).toEqual([
      "MATCHED",
      "MISSING_IN_2B",
      "MISSING_IN_BOOKS",
      "PROBABLE",
      "UNMATCHED",
    ]);

    // Every verdict the task names renders as a filter chip with its count.
    const chipCounts: [string, string][] = [
      ["MATCHED", "Matched · 1"],
      ["PROBABLE", "Probable · 1"],
      ["UNMATCHED", "Unmatched · 1"],
      ["MISSING_IN_2B", "Missing in 2B · 1"],
      ["MISSING_IN_BOOKS", "Missing in books · 1"],
    ];
    for (const [status, label] of chipCounts) {
      await expect(page.getByTestId(`itc-filter-${status}`)).toHaveText(label);
    }

    // 3. Status filter narrows the table.
    await page.getByTestId("itc-filter-MISSING_IN_2B").click();
    await expect(page.getByTestId("itc-row")).toHaveCount(1);
    await expect(page.getByTestId("itc-badge")).toHaveText("MISSING_IN_2B");
    await expect(page.getByTestId("itc-row")).toContainText(BOOKS_MISSING_2B);
    await page.getByTestId("itc-filter-ALL").click();
    await expect(page.getByTestId("itc-row")).toHaveCount(5);

    // 4. ITC summary prefill card — hand-checked on the fixture:
    //    books 4 x (9000 CGST + 9000 SGST) = 72000 paise = ₹720.00;
    //    2B eligible (9000+9000+4500+2700) x 2 = 50400 paise = ₹504.00;
    //    delta 21600 paise = ₹216.00.
    await expect(page.getByTestId("itc-summary-table")).toBeVisible();
    const summaryTotal = page.getByTestId("itc-summary-total");
    await expect(summaryTotal).toContainText("₹720.00");
    await expect(summaryTotal).toContainText("₹504.00");
    await expect(summaryTotal).toContainText("₹216.00");

    // 5. Chase-supplier list carries the MISSING_IN_2B document only.
    await expect(page.getByTestId("itc-chase-row")).toHaveCount(1);
    await expect(page.getByTestId("itc-chase-list")).toContainText(
      BOOKS_MISSING_2B,
    );

    // The books-vs-2B pairing: the MATCHED row carries its own invoice number
    // on both sides, and the 2B-only row shows as MISSING_IN_BOOKS.
    const matchedRow = page
      .getByTestId("itc-row")
      .filter({ hasText: BOOKS_MATCHED });
    await expect(matchedRow).toContainText(BOOKS_MATCHED);
    await expect(matchedRow.getByTestId("itc-badge")).toHaveText("MATCHED");
    const missingBooksRow = page
      .getByTestId("itc-row")
      .filter({ hasText: TWO_B_ONLY });
    await expect(missingBooksRow).toContainText("MISSING_IN_BOOKS");
  });
});

test.describe("9.4 ITC reachability audit (static)", () => {
  test("ShellNav.tsx links the /app/itc route", () => {
    // Grep, not eyeball — the same static-audit pattern e2e_phase8.py uses.
    const shell = readFileSync(
      join(process.cwd(), "components", "shared", "ShellNav.tsx"),
      "utf-8",
    );
    expect(shell).toContain("/app/itc/");
    expect(shell).toContain('key: "itc"');
    // The nav testids are template-built (`nav-link-${item.key}`), so the
    // literal `nav-link-itc` never appears in the source — assert the template
    // plus the itc key, which is what renders the testid.
    expect(shell).toContain("data-testid={`nav-link-${item.key}`}");
  });
});
