/**
 * Task 7.2 — Playwright E2E for the upload-to-output happy path.
 *
 * From login, a signed-in user:
 *   1. lands on the unified shell,
 *   2. clicks Upload for a GSTIN + period,
 *   3. uploads a minimal valid PDF,
 *   4. triggers dev-mode extraction,
 *   5. reviews the extracted draft,
 *   6. confirms it,
 *   7. navigates to returns output,
 *   8. downloads GSTR-1 and GSTR-3B JSON.
 *
 * Synthetic identities and GSTIN only; no real taxpayer data.
 */
import { expect, test, Page } from "@playwright/test";

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

const BACKEND = "http://127.0.0.1:8084";

function uniqueEmail(): string {
  return `test_${Date.now()}_${Math.random().toString(36).slice(2, 8)}@example.com`;
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
    body: JSON.stringify({ gstin, legal_name: `Happy Path Co ${Date.now()}` }),
  });
  expect([200, 201, 409]).toContain(res.status);
}

async function loginUi(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("login-identifier").fill(email);
  await page.getByTestId("login-request-otp").click();
  const banner = page.getByTestId("dev-otp");
  await expect(banner).toBeVisible();
  const text = await banner.textContent();
  const code = text!.match(/dev code:\s*(\d{6})/)![1];
  await page.getByTestId("login-otp").fill(code);
  await page.getByTestId("login-verify").click();
  await expect(page).toHaveURL(/\/app$/, { timeout: 10_000 });
}

test.describe("upload-to-output happy path", () => {
  test("login → upload → extract → review → confirm → download GSTR-1/3B", async ({
    page,
  }) => {
    const email = uniqueEmail();
    const token = await registerApi(email);
    const gstin = makeGstin(); // checksum-valid synthetic fixture
    await createGstAccount(token, gstin);

    await loginUi(page, email);

    // 1. Shell shows GST account card with upload link.
    await expect(page.getByTestId("gst-account-card")).toBeVisible({
      timeout: 10_000,
    });
    await page.getByTestId("upload-link").click();

    // 2. Upload page.
    await expect(page).toHaveURL(`/app/upload/${gstin}/092026`);
    await page.getByTestId("file-input").setInputFiles({
      name: "invoice.pdf",
      mimeType: "application/pdf",
      buffer: minimalPdf(),
    });
    await page.getByTestId("upload-submit").click();

    // 3. Wait for upload + extraction success.
    const success = page.getByTestId("upload-success");
    await expect(success).toBeVisible({ timeout: 30_000 });
    const statusText = await success.textContent();
    expect(statusText).toMatch(/Status:/);

    // Capture doc id from success text to use dev extraction endpoint via API.
    const docIdMatch = statusText!.match(/Document ID:\s*([0-9a-f-]{36})/i);
    expect(docIdMatch).toBeTruthy();
    const docId = docIdMatch![1];

    // 4. Trigger dev-mode synchronous extraction through the backend API.
    const extractRes = await fetch(
      `${BACKEND}/api/v1/documents/${docId}/extract`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
      },
    );
    expect(extractRes.status).toBe(200);

    // 5. Open review page.
    await page.goto(`/app/review/${gstin}/092026/${docId}`);
    await expect(page.getByText("Review & confirm")).toBeVisible({
      timeout: 10_000,
    });

    // If the draft has flags, this extraction will likely have none for the
    // minimal synthetic PDF (OCR will be empty, but the dev pipeline runs).
    // Confirm button must become enabled when clean.
    const confirmBtn = page.getByTestId("confirm-document");
    await expect(confirmBtn).toBeEnabled({ timeout: 5_000 });
    await confirmBtn.click();

    // 6. Success → navigate to returns output.
    await expect(page.getByTestId("review-success")).toBeVisible({
      timeout: 10_000,
    });
    await page.getByTestId("go-to-returns").click();
    await expect(page).toHaveURL(`/app/returns/${gstin}/092026`);

    // 7. Download GSTR-1 and GSTR-3B JSON.
    const [gstr1Download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("download-gstr1").click(),
    ]);
    expect(gstr1Download.suggestedFilename()).toMatch(/GSTR1-.*\.json/);

    const [gstr3bDownload] = await Promise.all([
      page.waitForEvent("download"),
      page.getByTestId("download-gstr3b").click(),
    ]);
    expect(gstr3bDownload.suggestedFilename()).toMatch(/GSTR3B-.*\.json/);
  });
});
