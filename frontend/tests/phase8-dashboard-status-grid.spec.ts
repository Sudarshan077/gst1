/**
 * Task 8.10 gate — Playwright: dashboard filing-status tracker
 * (PHASE8_PRODUCT_COMPLETENESS.md §3.8.10). Backend (8084) + frontend dev
 * server (9094) must be running; the backend needs PG:5436 + Redis:6380
 * (bootstrap_stack.py).
 *
 * done_when: the per-GSTIN × period status grid renders filed/draft/pending
 * for a SEEDED GSTIN (periods seeded through the real /returns/filed and
 * prepare endpoints so the statuses come from the server), while the existing
 * gst-account-card + upload-link testids stay intact. Synthetic fixtures only;
 * the GSTIN is checksum-valid by construction (makeGstin).
 */
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { expect, test, Page } from "@playwright/test";

const execFileAsync = promisify(execFile);
const BACKEND = "http://127.0.0.1:8084";
const REPO_ROOT = ".."; // specs run with cwd = frontend/

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

/** Attach a GSTIN to the logged-in user (POST /gst-accounts). */
async function addGstinViaApi(accessToken: string, gstin: string): Promise<void> {
  const res = await fetch(`${BACKEND}/api/v1/gst-accounts`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ gstin, legal_name: "Status Grid Co" }),
  });
  expect(res.status).toBe(200);
}

/** Seed a FILED period through the real filing endpoint. */
async function seedFiledPeriod(
  accessToken: string,
  gstin: string,
  fp: string,
): Promise<void> {
  const res = await fetch(
    `${BACKEND}/api/v1/gst-accounts/${gstin}/months/${fp}/filed`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
    },
  );
  expect(res.status).toBe(200);
}

/**
 * Seed a period status directly in the DB via scripts/seed_period_status.py.
 * Used only for READY_FOR_FILING (draft): the public API only creates
 * periods as OPEN (deadline engine) or FILED (/filed, GSP file), and the 8.10
 * grid must show the draft state too. Backend pytest seeds the same rows via
 * api_sessionmaker (test_business_mgmt_overview.py); this is the E2E-process
 * equivalent, run with the backend venv.
 */
async function seedPeriodStatus(
  gstin: string,
  fp: string,
  status: "OPEN" | "READY_FOR_FILING" | "FILED",
): Promise<void> {
  const { stdout } = await execFileAsync(
    "backend/.venv/Scripts/python.exe",
    ["scripts/seed_period_status.py", gstin, fp, status],
    { cwd: REPO_ROOT },
  );
  expect(stdout.trim()).toBe(status);
}

test.describe("dashboard filing-status tracker (/app)", () => {
  test("status grid renders filed/draft/pending per period for a seeded GSTIN", async ({
    page,
  }) => {
    const email = uniqueEmail();
    const accessToken = await registerViaApi(email);
    const gstin = makeGstin(); // checksum-valid synthetic fixture
    await addGstinViaApi(accessToken, gstin);

    // Seed statuses inside the CURRENT financial year (the overview endpoint
    // reports Apr..Mar of the running FY; periods outside it never render).
    const now = new Date();
    const fyStart = now.getMonth() + 1 >= 4 ? now.getFullYear() : now.getFullYear() - 1;
    const filedFp = `04${fyStart}`; // April -> FILED
    const draftFp = `05${fyStart}`; // May -> READY_FOR_FILING (draft)

    await seedFiledPeriod(accessToken, gstin, filedFp);
    await seedPeriodStatus(gstin, draftFp, "READY_FOR_FILING");
    // June onwards: no filings -> OPEN -> renders as pending.

    await loginViaUi(page, email);

    // Existing testids intact (task 7.2 / app tour contract).
    const card = page.getByTestId("gst-account-card").filter({ hasText: gstin });
    await expect(card).toBeVisible({ timeout: 15_000 });
    await expect(card.getByTestId("upload-link")).toBeVisible();
    await expect(card.getByTestId("upload-link")).toHaveAttribute(
      "href",
      `/app/upload/${gstin}/092026`,
    );

    // The new grid renders for this GSTIN.
    const grid = page.getByTestId(`filing-status-grid-${gstin}`);
    await expect(grid).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("filing-status-title").first()).toBeVisible();

    // A full FY is 12 periods (Apr..Mar) — same contract as the 8.3 overview.
    await expect(grid.getByTestId("filing-status-row")).toHaveCount(12);

    // filed: the seeded FILED period.
    const filedRow = grid
      .getByTestId("filing-status-row")
      .filter({ has: page.getByTestId("filing-status-chip") });
    const filedChip = grid
      .getByTestId("filing-status-row")
      .filter({ hasText: "Apr" })
      .getByTestId("filing-status-chip");
    await expect(filedChip).toHaveAttribute("data-status", "filed");
    await expect(filedChip).toHaveText("filed");

    // draft: the seeded READY_FOR_FILING period.
    const draftChip = grid
      .getByTestId("filing-status-row")
      .filter({ hasText: "May" })
      .getByTestId("filing-status-chip");
    await expect(draftChip).toHaveAttribute("data-status", "draft");
    await expect(draftChip).toHaveText("draft");

    // pending: an unseeded period (OPEN server-side).
    const pendingChip = grid
      .getByTestId("filing-status-row")
      .filter({ hasText: "Jun" })
      .getByTestId("filing-status-chip");
    await expect(pendingChip).toHaveAttribute("data-status", "pending");
    await expect(pendingChip).toHaveText("pending");

    // Quick actions land on the right period-scoped routes.
    const filedRowAgain = grid
      .getByTestId("filing-status-row")
      .filter({ hasText: "Apr" });
    await expect(filedRowAgain.getByTestId("grid-returns-link")).toHaveAttribute(
      "href",
      `/app/returns/${gstin}/${filedFp}`,
    );
    await expect(filedRowAgain.getByTestId("grid-upload-link")).toHaveAttribute(
      "href",
      `/app/upload/${gstin}/${filedFp}`,
    );

    // Statuses come from the server, not the client: reload and the grid
    // still shows the same three statuses.
    await page.reload();
    const cardAfter = page.getByTestId("gst-account-card").filter({ hasText: gstin });
    await expect(cardAfter).toBeVisible({ timeout: 15_000 });
    const gridAfter = page.getByTestId(`filing-status-grid-${gstin}`);
    await expect(gridAfter).toBeVisible({ timeout: 15_000 });
    await expect(
      gridAfter
        .getByTestId("filing-status-row")
        .filter({ hasText: "Apr" })
        .getByTestId("filing-status-chip"),
    ).toHaveAttribute("data-status", "filed");
    await expect(
      gridAfter
        .getByTestId("filing-status-row")
        .filter({ hasText: "May" })
        .getByTestId("filing-status-chip"),
    ).toHaveAttribute("data-status", "draft");

    void filedRow; // referenced for clarity above
  });
});