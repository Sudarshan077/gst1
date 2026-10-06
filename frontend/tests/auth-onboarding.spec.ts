/**
 * Task 0.7 gate — Playwright: unified onboarding, no role split (v4 model,
 * VERIFICATION_SWEEP.md Lens 2). Backend (8084) + frontend dev server (9094)
 * must be running; the backend needs PG:5436 + Redis:6380 (bootstrap_stack.py).
 *
 * Synthetic identities only — random email addresses; no real PII.
 */
import { expect, test, Page } from "@playwright/test";

const BACKEND = "http://127.0.0.1:8084";

function uniqueEmail(): string {
  return `test_${Date.now()}_${Math.random().toString(36).slice(2, 8)}@example.com`;
}

async function requestOtp(identifier: string, purpose: string) {
  const res = await fetch(`${BACKEND}/api/v1/auth/otp/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier, purpose }),
  });
  const body = (await res.json()) as {
    success: boolean;
    data?: { otp_sent: boolean; dev_otp?: string };
  };
  expect(body.success).toBe(true);
  return body.data!;
}

/** Wait for the dev OTP banner that the backend echoes in dev mode. */
async function waitForDevOtp(page: Page): Promise<string> {
  const banner = page.getByTestId("reg-dev-otp");
  await expect(banner).toBeVisible();
  const text = await banner.textContent();
  const match = text?.match(/dev code:\s*(\d{6})/);
  expect(match).toBeTruthy();
  return match![1];
}

/** Wait for the dev OTP banner on the login screen. */
async function waitForLoginDevOtp(page: Page): Promise<string> {
  const banner = page.getByTestId("dev-otp");
  await expect(banner).toBeVisible();
  const text = await banner.textContent();
  const match = text?.match(/dev code:\s*(\d{6})/);
  expect(match).toBeTruthy();
  return match![1];
}

test.describe("unified onboarding", () => {
  test("register has no role pick and lands on the unified shell", async ({
    page,
  }) => {
    const email = uniqueEmail();
    // The backend must know this identifier for REGISTER verify to auto-create the user.
    await requestOtp(email, "REGISTER");

    await page.goto("/register");
    // Lens 2 (VERIFICATION_SWEEP.md): no CA/business role selection may exist.
    await expect(page.getByTestId("register-client")).toHaveCount(0);
    await expect(page.getByTestId("register-ca")).toHaveCount(0);
    await page.getByTestId("reg-identifier").fill(email);
    await page.getByTestId("reg-request-otp").click();
    const devOtp = await waitForDevOtp(page);
    await page.getByTestId("reg-otp").fill(devOtp);
    await page.getByTestId("reg-verify").click();

    await expect(page).toHaveURL(/\/app$/, { timeout: 10_000 });
    await expect(page.getByTestId("shell-user")).toContainText("User");
  });

  test("login for existing user routes to the unified shell", async ({
    page,
  }) => {
    const email = uniqueEmail();
    await requestOtp(email, "REGISTER");
    const { dev_otp: regOtp } = await requestOtp(email, "REGISTER");
    expect(regOtp).toBeTruthy();
    const res = await fetch(`${BACKEND}/api/v1/auth/otp/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identifier: email, otp: regOtp }),
    });
    expect(res.status).toBe(200);

    await page.goto("/login");
    await page.getByTestId("login-identifier").fill(email);
    await page.getByTestId("login-request-otp").click();
    const pageOtp = await waitForLoginDevOtp(page);
    await page.getByTestId("login-otp").fill(pageOtp);
    await page.getByTestId("login-verify").click();

    // Wait for shell render; client-side navigation lands on the shell.
    await expect(page.getByTestId("shell-user")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page).toHaveURL(/\/app$/, { timeout: 10_000 });
  });

  test("shell lists GST accounts from /auth/me gst_accounts", async ({
    page,
  }) => {
    const email = uniqueEmail();
    await requestOtp(email, "REGISTER");
    const { dev_otp: regOtp } = await requestOtp(email, "REGISTER");
    const res = await fetch(`${BACKEND}/api/v1/auth/otp/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identifier: email, otp: regOtp }),
    });
    expect(res.status).toBe(200);

    await page.goto("/login");
    await page.getByTestId("login-identifier").fill(email);
    await page.getByTestId("login-request-otp").click();
    const pageOtp = await waitForLoginDevOtp(page);
    await page.getByTestId("login-otp").fill(pageOtp);
    await page.getByTestId("login-verify").click();

    await expect(page.getByTestId("shell-user")).toBeVisible({
      timeout: 10_000,
    });
    // A fresh user has no GST accounts — the empty state must render (never
    // the removed businesses/firm fields).
    await expect(page.getByText("No GST accounts linked yet")).toBeVisible({
      timeout: 10_000,
    });
  });
});

test.describe("route guard", () => {
  test("unauthenticated visitor is redirected to login", async ({ page }) => {
    await page.addInitScript(() => {
      document.cookie = "gst_session=; path=/; max-age=0";
    });
    await page.goto("/app");
    await expect(page).toHaveURL(/\/login/);
  });

  test("forged gst_session cookie without session is rejected", async ({
    page,
  }) => {
    await page.context().addCookies([
      { name: "gst_session", value: "1", domain: "127.0.0.1", path: "/" },
    ]);
    await page.goto("/ca");
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
  });

  test("authenticated user hitting /login is sent to the shell", async ({
    page,
  }) => {
    const email = uniqueEmail();
    await requestOtp(email, "REGISTER");

    await page.goto("/register");
    await page.getByTestId("reg-identifier").fill(email);
    await page.getByTestId("reg-request-otp").click();
    const devOtp = await waitForDevOtp(page);
    await page.getByTestId("reg-otp").fill(devOtp);
    await page.getByTestId("reg-verify").click();
    await expect(page).toHaveURL(/\/app$/, { timeout: 10_000 });

    await page.goto("/login");
    await expect(page).toHaveURL(/\/app$/, { timeout: 10_000 });
  });
});