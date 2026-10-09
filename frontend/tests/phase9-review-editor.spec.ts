/**
 * Task 9.1 gate — Playwright: full-field review editor (PHASE9_QA_SWEEP_FIXES.md
 * §3.9.1). Backend (8084) + frontend dev server (9094) must be running; the
 * backend needs PG:5436 + Redis:6380 (bootstrap_stack.py).
 *
 * done_when: edit buyer_gstin to a checksum-valid GSTIN -> saves (PUT draft)
 * -> persists after reload. Edit to a corrupted GSTIN -> rejected
 * client-side BEFORE the network (no PUT request reaches the server).
 * Synthetic fixtures only; GSTINs are checksum-valid by construction
 * (makeGstin, same rule as lib/validation/gstin.ts).
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

/** Corrupt a checksum-valid GSTIN: flip the check digit to a wrong one. */
function corruptGstin(gstin: string): string {
  const charset = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  const idx = charset.indexOf(gstin[14]);
  return `${gstin.slice(0, 14)}${charset[(idx + 1) % 36]}`;
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
  const body = (await verifyRes.json()) as {
    data: { access_token: string };
  };
  return body.data.access_token;
}

async function createGstAccount(token: string, gstin: string): Promise<void> {
  const res = await fetch(`${BACKEND}/api/v1/gst-accounts`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ gstin, legal_name: `Review Editor Co ${Date.now()}` }),
  });
  expect([200, 201, 409]).toContain(res.status);
}

async function loginUi(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("login-identifier").fill(email);
  await page.getByTestId("login-request-otp").click();
  const banner = page.getByTestId("dev-otp");
  // Explicit timeout: under the full suite the dev server + backend are contended.
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

test.describe("9.1 full-field review editor", () => {
  test("edit buyer_gstin valid -> persists after reload; corrupted -> rejected client-side", async ({
    page,
  }) => {
    const email = uniqueEmail();
    const token = await registerApi(email);
    const gstin = makeGstin(); // checksum-valid synthetic fixture
    await createGstAccount(token, gstin);
    const fp = "092026";
    await loginUi(page, email);
    const docId = await uploadAndExtract(page, token, gstin, fp);

    // Open the review page — the full editor section must render.
    await page.goto(`/app/review/${gstin}/${fp}/${docId}`);
    await expect(page.getByText("Review & confirm")).toBeVisible({
      timeout: 10_000,
    });
    const editorSection = page.getByText("Edit draft fields");
    await expect(editorSection).toBeVisible();
    const buyerInput = page.getByTestId("edit-buyer_gstin");
    await expect(buyerInput).toBeVisible();
    const originalBuyer = (await buyerInput.inputValue()) as string;
    expect(originalBuyer).toMatch(/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$/);

    // --- Case 1: corrupted GSTIN rejected client-side, BEFORE the network. ---
    const corrupted = corruptGstin(originalBuyer);
    expect(corrupted).not.toBe(originalBuyer); // checksum now wrong

    // Watch for any PUT request to the draft endpoint during this edit.
    let putWhileCorrupted = false;
    page.on("request", (req) => {
      if (
        req.method() === "PUT" &&
        req.url().includes(`/documents/${docId}/draft`)
      ) {
        putWhileCorrupted = true;
      }
    });
    await buyerInput.fill(corrupted);
    await buyerInput.blur();
    // Client-side rejection is shown inline; no network save happens.
    await expect(page.getByTestId("buyer_gstin-hint")).toContainText(
      /Invalid GSTIN/,
    );
    expect(putWhileCorrupted).toBe(false);
    // Server is the authority: confirm the corrupted value never landed.
    const draftRes = await fetch(`${BACKEND}/api/v1/documents/${docId}/draft`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const draftBody = (await draftRes.json()) as {
      data: { fields: Record<string, unknown> };
    };
    expect(draftBody.data.fields.buyer_gstin).toBe(originalBuyer);

    // --- Case 2: valid checksum GSTIN saves and persists after reload. ---
    const validBuyer = makeGstin(); // fresh checksum-valid synthetic fixture
    await buyerInput.fill(validBuyer);
    await buyerInput.blur();
    // Saved field clears the hint / shows no error.
    await expect(page.getByTestId("review-error")).toHaveCount(0);
    // The display pane reflects the new value.
    await expect(page.getByText(validBuyer).first()).toBeVisible();

    // Reload: the edited buyer_gstin must persist (server round-trip).
    await page.goto(`/app/review/${gstin}/${fp}/${docId}`);
    await expect(page.getByText("Review & confirm")).toBeVisible({
      timeout: 10_000,
    });
    const buyerAfterReload = page.getByTestId("edit-buyer_gstin");
    await expect(buyerAfterReload).toHaveValue(validBuyer, { timeout: 10_000 });
  });
});