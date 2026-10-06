/**
 * Phase 4 frontend lens — GSP filing + IRN board are reachable from the
 * unified shell and exercise the Phase 4 backend routes.
 */
import { expect, test } from "@playwright/test";

const BACKEND = "http://127.0.0.1:8084";

function uniqueEmail(): string {
  return `test_${Date.now()}_${Math.random().toString(36).slice(2, 8)}@example.com`;
}

async function registerApi(email: string) {
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
    data: { access_token: string; user: { id: string } };
  };
  return body.data;
}

async function createGstAccount(token: string, gstin: string) {
  const res = await fetch(`${BACKEND}/api/v1/gst-accounts`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ gstin, legal_name: `Phase 4 Test Co ${Date.now()}` }),
  });
  // Accept 200 (created) or 409 (already exists from a previous run)
  expect([200, 409]).toContain(res.status);
}

test.describe("Phase 4 filing surfaces", () => {
  test("GSP filing hub renders for a GSTIN + period", async ({ page }) => {
    const email = uniqueEmail();
    const { access_token } = await registerApi(email);
    const gstin = "27AYCPY8898Z1ZB"; // checksum-valid synthetic vector
    await createGstAccount(access_token, gstin);

    await page.goto("/login");
    await page.getByTestId("login-identifier").fill(email);
    await page.getByTestId("login-request-otp").click();
    const otp = await page.getByTestId("dev-otp").textContent();
    const code = otp!.match(/dev code:\s*(\d{6})/)![1];
    await page.getByTestId("login-otp").fill(code);
    await page.getByTestId("login-verify").click();
    await expect(page).toHaveURL(/\/app$/, { timeout: 10_000 });

    const fp = "092026";
    await page.goto(`/app/file/${gstin}/${fp}`);
    await expect(page.getByText("Direct filing")).toBeVisible();
    await expect(page.getByTestId("file-gstr1-btn")).toBeVisible();
    await expect(page.getByTestId("file-gstr3b-btn")).toBeVisible();
  });

  test("IRN board renders for a GSTIN + period", async ({ page }) => {
    const email = uniqueEmail();
    const { access_token } = await registerApi(email);
    const gstin = "27AYCPY8898Z1ZB"; // checksum-valid synthetic vector
    await createGstAccount(access_token, gstin);

    await page.goto("/login");
    await page.getByTestId("login-identifier").fill(email);
    await page.getByTestId("login-request-otp").click();
    const otp = await page.getByTestId("dev-otp").textContent();
    const code = otp!.match(/dev code:\s*(\d{6})/)![1];
    await page.getByTestId("login-otp").fill(code);
    await page.getByTestId("login-verify").click();
    await expect(page).toHaveURL(/\/app$/, { timeout: 10_000 });

    const fp = "092026";
    await page.goto(`/app/einvoice/${gstin}/${fp}`);
    await expect(page.getByText("E-Invoices / IRN")).toBeVisible();
    await expect(page.getByTestId("generate-irn-btn")).toBeVisible();
  });
});
