/**
 * Task 9.5 gate — Playwright: WARN-tier advisory flags render in the review
 * page's amber panel and do NOT block confirmation
 * (PHASE9_QA_SWEEP_FIXES.md §3.9.5).
 *
 * Backend (8084) + frontend dev server (9094) must be running; the backend
 * needs PG:5436 + Redis:6380 (bootstrap_stack.py).
 *
 * The backend validator emits `severity: "WARN"` for advisory rules — a stale
 * invoice date (>30 days before the period end) and an HSN/SAC shorter than 6
 * digits. `confirm_draft` filters BLOCK only, so a WARN-only draft confirms
 * with 200. This spec drives the real path: upload → dev-extract → PUT a stale
 * invoice_date → review page shows the WARN flag as advisory (non-blocking) →
 * confirm succeeds.
 *
 * Synthetic fixtures only; the GSTIN is checksum-valid by construction
 * (makeGstin, same mod-36 rule as app/core/gstin.py).
 */
import { expect, test, Page } from "@playwright/test";

const BACKEND = "http://127.0.0.1:8084";

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

function minimalPdf(): Buffer {
  return Buffer.from(
    "%PDF-1.4\n" +
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
    body: JSON.stringify({ gstin, legal_name: `Warn Panel Co ${Date.now()}` }),
  });
  expect([200, 201, 409]).toContain(res.status);
}

async function loginUi(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("login-identifier").fill(email);
  await page.getByTestId("login-request-otp").click();
  const banner = page.getByTestId("dev-otp");
  await expect(banner).toBeVisible({ timeout: 15_000 });
  const text = await banner.textContent();
  const code = text!.match(/dev code:\s*(\d{6})/)![1];
  await page.getByTestId("login-otp").fill(code);
  await page.getByTestId("login-verify").click();
  await expect(page).toHaveURL(/\/app$/, { timeout: 10_000 });
}

/** Upload one minimal PDF for (gstin, fp) and run dev extraction; returns docId. */
async function uploadAndExtract(
  page: Page,
  token: string,
  gstin: string,
  fp: string,
): Promise<string> {
  await page.goto(`/app/upload/${gstin}/${fp}`);
  await page.getByTestId("file-input").setInputFiles({
    name: "invoice.pdf",
    mimeType: "application/pdf",
    buffer: minimalPdf(),
  });
  await page.getByTestId("upload-submit").click();
  const success = page.getByTestId("upload-success");
  await expect(success).toBeVisible({ timeout: 30_000 });
  const statusText = await success.textContent();
  const docIdMatch = statusText!.match(/Document ID:\s*([0-9a-f-]{36})/i);
  expect(docIdMatch).toBeTruthy();
  const docId = docIdMatch![1];

  const extractRes = await fetch(`${BACKEND}/api/v1/documents/${docId}/extract`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
  });
  expect(extractRes.status).toBe(200);
  return docId;
}

test.describe("9.5 WARN-tier advisory flags", () => {
  test("stale invoice date -> WARN advisory in amber panel, confirm still succeeds", async ({
    page,
  }) => {
    const email = uniqueEmail();
    const token = await registerApi(email);
    const gstin = makeGstin(); // checksum-valid synthetic fixture
    await createGstAccount(token, gstin);
    const fp = "092026"; // period end 30 Sep 2026
    await loginUi(page, email);
    const docId = await uploadAndExtract(page, token, gstin, fp);

    // Drive a stale invoice date through the real PUT draft path.
    // 2026-08-01 is 60 days before the 2026-09-30 period end -> STALE_INVOICE_DATE.
    const putRes = await fetch(`${BACKEND}/api/v1/documents/${docId}/draft`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ invoice_date: "2026-08-01" }),
    });
    expect(putRes.status).toBe(200);
    const putBody = (await putRes.json()) as {
      data: { flags: { rule: string; severity: string }[] };
    };
    const warnFlags = putBody.data.flags.filter((f) => f.rule === "STALE_INVOICE_DATE");
    expect(warnFlags.length).toBe(1);
    expect(warnFlags[0].severity).toBe("WARN");

    // Review page: the amber flags panel renders the WARN flag as advisory.
    await page.goto(`/app/review/${gstin}/${fp}/${docId}`);
    await expect(page.getByText("Review & confirm")).toBeVisible({
      timeout: 10_000,
    });
    const panel = page.getByTestId("review-flags");
    await expect(panel).toBeVisible();
    await expect(panel).toContainText("STALE_INVOICE_DATE (WARN)");
    await expect(page.getByTestId("review-advisory-note")).toContainText(
      /advisory/i,
    );
    await expect(page.getByTestId("review-advisory-note")).toContainText(
      /non-blocking/i,
    );

    // Advisory must NOT block: the confirm button is enabled and the hint
    // says the flags are non-blocking.
    const confirmBtn = page.getByTestId("confirm-document");
    await expect(confirmBtn).toBeEnabled();

    // Confirm succeeds end-to-end — WARN-only draft -> 200.
    await confirmBtn.click();
    await expect(page.getByTestId("review-success")).toBeVisible({
      timeout: 10_000,
    });
  });
});
