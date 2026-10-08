/**
 * Task 8.8 gate — Playwright: manage businesses (PHASE8_PRODUCT_COMPLETENESS.md
 * §3.8.8). Backend (8084) + frontend dev server (9094) must be running; the
 * backend needs PG:5436 + Redis:6380 (bootstrap_stack.py).
 *
 * done_when: add a generated GSTIN -> appears in list -> open detail -> edit
 * legal_name -> persists. Client-side checksum validation is exercised with a
 * deliberately-corrupted GSTIN. Reachable by clicking the nav. Synthetic
 * fixtures only; the GSTIN is checksum-valid by construction (make_gstin).
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

/** Server is the authority: read the account straight from the backend. */
async function fetchAccountViaApi(
  email: string,
  gstin: string,
): Promise<{ legal_name: string; role: string }> {
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
  const detail = await fetch(`${BACKEND}/api/v1/gst-accounts/${gstin}`, {
    headers: { Authorization: `Bearer ${tokens.access_token}` },
  });
  expect(detail.status).toBe(200);
  const body = (await detail.json()) as {
    data: { legal_name: string; role: string };
  };
  return body.data;
}

test.describe("manage businesses (/app/businesses)", () => {
  test("add a generated GSTIN -> list -> detail -> edit legal_name -> persists", async ({
    page,
  }) => {
    const email = uniqueEmail();
    await registerViaApi(email);
    await loginViaUi(page, email);

    // Reachable by clicking the nav (8.5 gate — never direct URL only).
    await page.getByTestId("nav-link-businesses").click();
    await expect(page).toHaveURL(/\/app\/businesses$/);
    await expect(page.getByTestId("business-list")).toBeVisible({ timeout: 15_000 });

    // Fresh account: designed empty state.
    await expect(page.getByText("No businesses yet")).toBeVisible();

    const gstin = makeGstin(); // checksum-valid synthetic fixture
    const legalName = `Test Biz Co ${Date.now()}`;

    // Add the business through the form.
    await page.getByTestId("business-add-gstin").fill(gstin);
    await page.getByTestId("business-add-name").fill(legalName);
    await page.getByTestId("business-add-submit").click();

    // It appears in the list without a reload.
    await expect(
      page.getByTestId("business-card").filter({ hasText: gstin }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.getByTestId("business-card-name").filter({ hasText: legalName }),
    ).toBeVisible();

    // Server is the authority: the account really exists.
    const created = await fetchAccountViaApi(email, gstin);
    expect(created.legal_name).toBe(legalName);
    expect(created.role).toBe("ADMIN");

    // Open the detail page from the list.
    await page
      .getByTestId("business-card")
      .filter({ hasText: gstin })
      .getByTestId("business-open-link")
      .click();
    await expect(page).toHaveURL(new RegExp(`/app/businesses/${gstin}$`), {
      timeout: 15_000,
    });
    await expect(page.getByTestId("business-detail-title")).toHaveText(legalName);
    await expect(page.getByTestId("business-field-gstin")).toHaveText(gstin);
    await expect(page.getByTestId("business-fy-status")).toBeVisible();

    // Edit legal_name -> save.
    const renamed = `${legalName} Renamed`;
    await expect(page.getByTestId("business-legal-name")).toHaveValue(legalName, {
      timeout: 15_000,
    });
    await page.getByTestId("business-legal-name").fill(renamed);
    await expect(page.getByTestId("business-save")).toBeEnabled();
    await page.getByTestId("business-save").click();
    await expect(page.getByTestId("business-saved")).toBeVisible({ timeout: 15_000 });

    // Persists after a full reload (fresh GET overview).
    await page.reload();
    await expect(page.getByTestId("business-legal-name")).toHaveValue(renamed, {
      timeout: 15_000,
    });
    await expect(page.getByTestId("business-detail-title")).toHaveText(renamed);

    // Server is the authority: the rename really persisted.
    const updated = await fetchAccountViaApi(email, gstin);
    expect(updated.legal_name).toBe(renamed);
  });

  test("client-side mod-36 checksum rejects a corrupted GSTIN before submit", async ({
    page,
  }) => {
    const email = uniqueEmail();
    await registerViaApi(email);
    await loginViaUi(page, email);
    await page.getByTestId("nav-link-businesses").click();
    await expect(page).toHaveURL(/\/app\/businesses$/);

    const bad = makeGstin();
    const corrupted = `${bad.slice(0, 14)}${bad[14] === "0" ? "1" : "0"}`; // checksum now wrong

    await page.getByTestId("business-add-gstin").fill(corrupted);
    await page.getByTestId("business-add-name").fill("Checksum Reject Co");
    await page.getByTestId("business-add-submit").click();

    await expect(page.getByTestId("business-add-error")).toBeVisible();
    await expect(page.getByTestId("business-add-error")).toContainText(
      /checksum|Invalid GSTIN/i,
    );

    // Nothing was created: no card with the corrupted GSTIN.
    await expect(
      page.getByTestId("business-card").filter({ hasText: corrupted }),
    ).toHaveCount(0);
  });
});