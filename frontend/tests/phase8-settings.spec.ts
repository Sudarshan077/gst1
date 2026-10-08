/**
 * Task 8.7 gate — Playwright: /app/settings (PHASE8_PRODUCT_COMPLETENESS.md
 * §3.8.7). Backend (8084) + frontend dev server (9094) must be running; the
 * backend needs PG:5436 + Redis:6380 (bootstrap_stack.py).
 *
 * done_when: reachable by clicking the nav; toggle a notification pref ->
 * save -> persists; TOTP entry links through; sign-out-everywhere wires to
 * POST /auth/logout-all. Synthetic identity only.
 */
import { expect, test, Page } from "@playwright/test";
import { totpCode } from "./totp-utils";

const BACKEND = "http://127.0.0.1:8084";

function uniqueEmail(): string {
  return `test_${Date.now()}_${Math.random().toString(36).slice(2, 8)}@example.com`;
}

/** Register the user via the backend API (dev OTP is echoed in the response). */
async function registerViaApi(email: string): Promise<void> {
  const res = await fetch(`${BACKEND}/api/v1/auth/otp/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier: email, purpose: "REGISTER" }),
  });
  const body = (await res.json()) as {
    success: boolean;
    data?: { otp_sent: boolean; dev_otp?: string };
  };
  expect(body.success).toBe(true);
  expect(body.data?.dev_otp).toBeTruthy();
  const verify = await fetch(`${BACKEND}/api/v1/auth/otp/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier: email, otp: body.data!.dev_otp }),
  });
  expect(verify.status).toBe(200);
}

/** Log the registered user in through the real login screen. */
async function loginViaUi(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("login-identifier").fill(email);
  await page.getByTestId("login-request-otp").click();
  const banner = page.getByTestId("dev-otp");
  // Explicit timeout: under the full suite the dev server + backend are contended.
  await expect(banner).toBeVisible({ timeout: 15_000 });
  const match = (await banner.textContent())?.match(/dev code:\s*(\d{6})/);
  expect(match).toBeTruthy();
  await page.getByTestId("login-otp").fill(match![1]);
  await page.getByTestId("login-verify").click();
  await expect(page).toHaveURL(/\/app$/, { timeout: 10_000 });
}

/** Read the raw prefs column straight from the backend (server is authority). */
async function fetchPrefsViaApi(email: string): Promise<Record<string, unknown>> {
  const req = await fetch(`${BACKEND}/api/v1/auth/otp/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier: email, purpose: "LOGIN" }),
  });
  const reqBody = (await req.json()) as { data?: { dev_otp?: string } };
  expect(reqBody.data?.dev_otp).toBeTruthy();
  const verify = await fetch(`${BACKEND}/api/v1/auth/otp/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier: email, otp: reqBody.data!.dev_otp }),
  });
  expect(verify.status).toBe(200);
  const tokens = ((await verify.json()) as { data: { access_token: string } }).data;
  const settings = await fetch(`${BACKEND}/api/v1/me/settings`, {
    headers: { Authorization: `Bearer ${tokens.access_token}` },
  });
  expect(settings.status).toBe(200);
  const data = (await settings.json()) as {
    data: { notification_preferences: Record<string, unknown> | null };
  };
  return data.data.notification_preferences ?? {};
}

test.describe("settings screen (/app/settings)", () => {
  test("nav click opens settings; toggle pref -> save -> persists after reload", async ({
    page,
  }) => {
    const email = uniqueEmail();
    await registerViaApi(email);
    await loginViaUi(page, email);

    // Reachable by clicking the nav (8.5 gate — never direct URL only).
    await page.getByTestId("nav-link-settings").click();
    await expect(page).toHaveURL(/\/app\/settings$/);

    // Fresh account: both channels default on. Explicit timeouts: the full
    // suite runs against a contended dev backend (profile spec does the same).
    const emailToggle = page.getByTestId("settings-pref-email");
    const inAppToggle = page.getByTestId("settings-pref-in_app");
    await expect(emailToggle).toBeChecked({ timeout: 15_000 });
    await expect(inAppToggle).toBeChecked({ timeout: 15_000 });
    await expect(page.getByTestId("settings-save")).toBeDisabled();

    // Toggle a notification pref -> save -> saved state.
    await emailToggle.click();
    await expect(emailToggle).not.toBeChecked({ timeout: 15_000 });
    await expect(page.getByTestId("settings-save")).toBeEnabled({ timeout: 15_000 });
    await page.getByTestId("settings-save").click();
    await expect(page.getByTestId("settings-saved")).toBeVisible({ timeout: 15_000 });

    // Persist after full reload (fresh GET /me/settings).
    await page.reload();
    await expect(page.getByTestId("settings-pref-email")).not.toBeChecked({
      timeout: 15_000,
    });
    await expect(page.getByTestId("settings-pref-in_app")).toBeChecked({
      timeout: 15_000,
    });
    await expect(page.getByTestId("settings-save")).toBeDisabled({
      timeout: 15_000,
    });

    // Server is the authority: the prefs column really holds the toggle.
    const prefs = await fetchPrefsViaApi(email);
    expect(prefs.email).toBe(false);
    expect(prefs.in_app).toBe(true);
  });

  test("TOTP entry links through to the enrollment flow and reflects enabled state", async ({
    page,
  }) => {
    const email = uniqueEmail();
    await registerViaApi(email);
    await loginViaUi(page, email);
    await page.getByTestId("nav-link-settings").click();
    await expect(page).toHaveURL(/\/app\/settings$/);

    // Disabled state before enrollment.
    await expect(page.getByTestId("settings-totp-status")).toHaveText("Disabled");

    // The entry links through to /totp (existing enrollment screen).
    await page.getByTestId("settings-totp-link").click();
    await expect(page).toHaveURL(/\/totp$/);
    await page.getByTestId("totp-begin").click();
    const secret = (await page.getByTestId("totp-secret").textContent())?.trim() ?? "";
    expect(secret.length).toBeGreaterThan(10);
    await page.getByTestId("totp-code").fill(totpCode(secret));
    await page.getByTestId("totp-verify-btn").click();
    await expect(page.getByTestId("totp-enabled-banner")).toBeVisible({
      timeout: 15_000,
    });
    await page.getByTestId("totp-continue").click();
    await expect(page).toHaveURL(/\/app$/, { timeout: 10_000 });

    // Settings now reflects TOTP as enabled.
    await page.getByTestId("nav-link-settings").click();
    await expect(page.getByTestId("settings-totp-status")).toHaveText("Enabled", {
      timeout: 15_000,
    });
  });

  test("sign-out-everywhere revokes the other device's session", async ({
    browser,
  }) => {
    const email = uniqueEmail();
    await registerViaApi(email);

    // Device A: login in a second context and leave it parked on /app.
    const ctxA = await browser.newContext();
    const pageA = await ctxA.newPage();
    await loginViaUi(pageA, email);
    await ctxA.storageState(); // no-op touch; pageA stays authenticated

    // Device B: this test's page — revoke everywhere from settings.
    // (registerViaApi + 2 device logins = 3 families; assert >= 2, exact
    // value depends on how many API-side families the register minted.)
    const ctxB = await browser.newContext();
    const pageB = await ctxB.newPage();
    await loginViaUi(pageB, email);
    await pageB.getByTestId("nav-link-settings").click();
    const beforeEl = pageB.getByTestId("settings-active-sessions");
    await expect(beforeEl).not.toHaveText("0", { timeout: 15_000 });
    const before = Number(await beforeEl.textContent());
    expect(before).toBeGreaterThanOrEqual(2);

    await pageB.getByTestId("settings-signout-everywhere").click();
    await expect(pageB.getByTestId("settings-revoked-info")).toBeVisible({
      timeout: 15_000,
    });
    await expect(pageB.getByTestId("settings-revoked-info")).toContainText(
      new RegExp(`Signed out ${before} device`),
    );
    await expect(pageB.getByTestId("settings-active-sessions")).toHaveText("0");

    // Device A's refresh family is dead: a reload can no longer refresh.
    await pageA.reload();
    await expect(pageA).toHaveURL(/\/login/, { timeout: 15_000 });
    await ctxA.close();
    await ctxB.close();
  });
});