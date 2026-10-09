/**
 * Task 9.3 gate — Playwright: dashboard empty-state CTA
 * (PHASE9_QA_SWEEP_FIXES.md §3.9.3). Backend (8084) + frontend dev server
 * (9094) must be running; the backend needs PG:5436 + Redis:6380
 * (bootstrap_stack.py).
 *
 * done_when:
 *  - a fresh user with ZERO GSTINs sees the primary
 *    "+ Link or Register GSTIN" CTA in the dashboard empty state
 *    (data-testid `empty-link-gstin`) and clicking it navigates to
 *    /app/businesses (the Phase-8 add-GSTIN flow);
 *  - the existing empty-state copy ("No GST accounts linked yet") stays;
 *  - additive: once a GSTIN is attached the CTA is gone and the existing
 *    `gst-account-card` + `upload-link` testids still render.
 *
 * Synthetic fixtures only; GSTINs are checksum-valid by construction
 * (same mod-36 rule as lib/validation/gstin.ts). No new backend.
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

/** Register the user via the backend API (dev OTP is echoed in the response). */
async function registerViaApi(email: string): Promise<string> {
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
  const tokens = ((await verify.json()) as { data: { access_token: string } }).data;
  return tokens.access_token;
}

/** Attach a GSTIN to the logged-in user (POST /gst-accounts). */
async function addGstinViaApi(accessToken: string, gstin: string): Promise<void> {
  const res = await fetch(`${BACKEND}/api/v1/gst-accounts`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ gstin, legal_name: "Empty State CTA Co" }),
  });
  expect([200, 201, 409]).toContain(res.status);
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

test.describe("dashboard empty-state CTA (/app)", () => {
  test("fresh user with 0 GSTINs sees the CTA and it lands on /app/businesses", async ({
    page,
  }) => {
    const email = uniqueEmail();
    await registerViaApi(email); // no GSTIN attached -> empty state
    await loginViaUi(page, email);

    // Existing empty-state copy stays (additive change).
    await expect(page.getByText("No GST accounts linked yet")).toBeVisible({
      timeout: 15_000,
    });

    // The new primary CTA renders and points at the add-GSTIN flow.
    const cta = page.getByTestId("empty-link-gstin");
    await expect(cta).toBeVisible();
    await expect(cta).toHaveText("+ Link or Register GSTIN");
    await expect(cta).toHaveAttribute("href", "/app/businesses");

    // No accounts -> no account card yet.
    await expect(page.getByTestId("gst-account-card")).toHaveCount(0);

    // Clicking navigates to the Phase-8 add-GSTIN screen.
    await cta.click();
    await expect(page).toHaveURL(/\/app\/businesses$/, { timeout: 10_000 });
    // That screen is the add-GSTIN flow: its "no businesses yet" state + form.
    await expect(page.getByText("No businesses yet")).toBeVisible({
      timeout: 15_000,
    });
  });

  test("CTA is gone once a GSTIN exists; card + upload-link testids stay", async ({
    page,
  }) => {
    const email = uniqueEmail();
    const accessToken = await registerViaApi(email);
    const gstin = makeGstin(); // checksum-valid synthetic fixture
    await addGstinViaApi(accessToken, gstin);
    await loginViaUi(page, email);

    // Additive contract: the existing card + upload-link testids still render.
    const card = page.getByTestId("gst-account-card").filter({ hasText: gstin });
    await expect(card).toBeVisible({ timeout: 15_000 });
    await expect(card.getByTestId("upload-link")).toBeVisible();
    await expect(card.getByTestId("upload-link")).toHaveAttribute(
      "href",
      `/app/upload/${gstin}/092026`,
    );

    // The empty-state CTA belongs to the zero-GSTIN state only.
    await expect(page.getByTestId("empty-link-gstin")).toHaveCount(0);
  });
});
