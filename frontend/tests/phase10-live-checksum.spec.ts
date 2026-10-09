/**
 * Task 10.4 gate — Playwright: live mod-36 checksum feedback on the Add
 * Business form (PHASE10_BUG_SWEEP_FIXES.md §10.4, FRONTEND_SPECIFICATION.md
 * §3.8 / §4 "GSTIN input — client-side checksum for instant feedback").
 * Backend (8084) + frontend dev server (9094) must be running; the backend
 * needs PG:5436 + Redis:6380 (bootstrap_stack.py).
 *
 * done_when:
 *  - typing a 15-character GSTIN whose mod-36 check digit is wrong surfaces the
 *    inline error immediately — WITHOUT clicking submit;
 *  - the live error clears once the check digit is valid again;
 *  - submit-button gating for non-15-char input is unchanged (disabled at 14
 *    chars, enabled at a valid 15);
 *  - the existing business-add-* testids and the submit-time error still work.
 *
 * Synthetic identity and GSTIN only; the GSTIN is checksum-valid by
 * construction (mod-36 makeGstin, same rule as lib/validation/gstin.ts).
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
function corruptCheckDigit(gstin: string): string {
  return `${gstin.slice(0, 14)}${gstin[14] === "0" ? "1" : "0"}`;
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
    data?: { dev_otp?: string };
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
  await expect(banner).toBeVisible({ timeout: 15_000 });
  const match = (await banner.textContent())?.match(/dev code:\s*(\d{6})/);
  expect(match).toBeTruthy();
  await page.getByTestId("login-otp").fill(match![1]);
  await page.getByTestId("login-verify").click();
  await expect(page).toHaveURL(/\/app$/, { timeout: 10_000 });
}

/** Reach the businesses screen through the nav (never direct-URL only). */
async function openBusinesses(page: Page, email: string): Promise<void> {
  await registerViaApi(email);
  await loginViaUi(page, email);
  await page.getByTestId("nav-link-businesses").click();
  await expect(page).toHaveURL(/\/app\/businesses$/);
  await expect(page.getByTestId("business-add-gstin")).toBeVisible({
    timeout: 15_000,
  });
}

test.describe("10.4 live checksum feedback (/app/businesses)", () => {
  test("a 15-char GSTIN with a bad check digit shows the inline error before submit", async ({
    page,
  }) => {
    await openBusinesses(page, uniqueEmail());

    const corrupted = corruptCheckDigit(makeGstin()); // 15 chars, bad check digit
    expect(corrupted).toHaveLength(15);

    // Type only — no click on business-add-submit.
    await page.getByTestId("business-add-gstin").fill(corrupted);

    const liveError = page.getByTestId("business-add-live-error");
    await expect(liveError).toBeVisible({ timeout: 5_000 });
    await expect(liveError).toContainText(/checksum|mod-36|check digit/i);

    // Proven to be the LIVE error, not the submit-time one.
    await expect(page.getByTestId("business-add-error")).toHaveCount(0);

    // The input itself carries the invalid affordance.
    await expect(page.getByTestId("business-add-gstin")).toHaveAttribute(
      "aria-invalid",
      "true",
    );

    // Fixing the check digit clears the live error with no submit.
    await page.getByTestId("business-add-gstin").fill(makeGstin());
    await expect(liveError).toHaveCount(0, { timeout: 5_000 });
  });

  test("submit gating for non-15-char input is unchanged", async ({ page }) => {
    await openBusinesses(page, uniqueEmail());

    const gstin = makeGstin(); // checksum-valid
    const submit = page.getByTestId("business-add-submit");

    // 14 chars: still gated (unchanged behaviour), no live error yet.
    await page.getByTestId("business-add-gstin").fill(gstin.slice(0, 14));
    await page.getByTestId("business-add-name").fill("Gating Co");
    await expect(submit).toBeDisabled();
    await expect(page.getByTestId("business-add-live-error")).toHaveCount(0);

    // 15 valid chars: enabled and clean.
    await page.getByTestId("business-add-gstin").fill(gstin);
    await expect(submit).toBeEnabled();
    await expect(page.getByTestId("business-add-live-error")).toHaveCount(0);
  });
});
