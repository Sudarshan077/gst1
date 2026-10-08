/**
 * Task 8.6 gate — Playwright: /app/profile (PHASE8_PRODUCT_COMPLETENESS.md
 * §3.8.6). Backend (8084) + frontend dev server (9094) must be running; the
 * backend needs PG:5436 + Redis:6380 (bootstrap_stack.py).
 *
 * done_when: reachable by clicking the nav; edit name -> save -> persists
 * after reload; email field read-only. Synthetic identity only.
 */
import { expect, test, Page } from "@playwright/test";

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
  await expect(banner).toBeVisible();
  const match = (await banner.textContent())?.match(/dev code:\s*(\d{6})/);
  expect(match).toBeTruthy();
  await page.getByTestId("login-otp").fill(match![1]);
  await page.getByTestId("login-verify").click();
  await expect(page).toHaveURL(/\/app$/, { timeout: 10_000 });
}

test.describe("profile screen (/app/profile)", () => {
  test("nav click opens profile; edit name -> save -> persists after reload; email read-only", async ({
    page,
  }) => {
    const email = uniqueEmail();
    await registerViaApi(email);
    await loginViaUi(page, email);

    // Reachable by clicking the nav (8.5 gate — never direct URL only).
    await page.getByTestId("nav-link-profile").click();
    await expect(page).toHaveURL(/\/app\/profile$/);

    // Profile renders from GET /me/profile.
    const emailInput = page.getByTestId("profile-email");
    await expect(emailInput).toBeVisible();
    await expect(emailInput).toHaveValue(email);
    // Email is read-only (8.1 contract: the login credential).
    expect(await emailInput.getAttribute("readonly")).not.toBeNull();
    await expect(emailInput).toBeDisabled();

    const nameInput = page.getByTestId("profile-name-input");
    await expect(nameInput).toBeVisible();

    // Inline edit -> save -> saved state. Explicit timeouts: under the full
    // suite the dev server + backend are contended and the PATCH can exceed
    // Playwright's 5s default expect timeout.
    const newName = `Renamed ${Math.random().toString(36).slice(2, 8)}`;
    await nameInput.fill(newName);
    await expect(page.getByTestId("profile-save")).toBeEnabled();
    await page.getByTestId("profile-save").click();
    await expect(page.getByTestId("profile-saved")).toBeVisible({ timeout: 15_000 });

    // Shell user chip stays in sync after the rename.
    await expect(page.getByTestId("shell-user")).toContainText(newName);

    // Persistence: full reload (fresh page load + fresh GET /me/profile).
    await page.reload();
    await expect(page.getByTestId("profile-email")).toHaveValue(email, {
      timeout: 15_000,
    });
    await expect(page.getByTestId("profile-name-input")).toHaveValue(newName);
    await expect(page.getByTestId("shell-user")).toContainText(newName);
  });
});