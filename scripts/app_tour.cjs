/**
 * app_tour.cjs — drive the GST Filing App through its own UI and capture evidence.
 *
 * Usage (NODE_PATH is required: node resolves modules relative to the script):
 *   cd D:/gst_filing_app/frontend
 *   NODE_PATH="D:/gst_filing_app/frontend/node_modules" node ../scripts/app_tour.cjs
 *
 * Output: prints one [STEP] line per verified screen (that log IS the evidence),
 * writes screenshots to ./docs/demo-screenshots/ and a JSON report to
 * ./docs/demo-screenshots/tour-report.json.
 *
 * Prereqs: backend :8084, frontend :9094, demo user seeded via scripts/seed_demo.py.
 * The tour navigates via the app's OWN links (keeps the in-memory bearer token);
 * it re-enters through /app after any full page load so the shell re-runs silentRefresh().
 */
const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const FRONTEND = "http://127.0.0.1:9094";
const BACKEND = "http://127.0.0.1:8084";
const EMAIL = "demo.tony@example.com";
const FP = "092026";
const OUT = path.resolve(__dirname, "..", "docs", "demo-screenshots");
fs.mkdirSync(OUT, { recursive: true });

const steps = [];
function step(n, title, evidence) {
  const line = `[STEP] ${n} | ${title} | ${evidence}`;
  console.log(line);
  steps.push({ n, title, evidence });
}

function makeGstin(state) {
  const L = "ABCDEFGHIJKLMNOPQRSTUVWXYZ", D = "0123456789";
  const pan = Array.from({ length: 5 }, () => L[Math.floor(Math.random() * 26)]).join("") +
    Array.from({ length: 4 }, () => D[Math.floor(Math.random() * 10)]).join("") +
    L[Math.floor(Math.random() * 26)];
  const first14 = `${state}${pan}1Z`;
  const cs = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ", w = [1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2];
  let total = 0;
  for (let i = 0; i < 14; i += 1) { const p = cs.indexOf(first14[i]) * w[i]; total += Math.floor(p / 36) + (p % 36); }
  return `${first14}${cs[(36 - (total % 36)) % 36]}`;
}

function minimalPdf() {
  return Buffer.from(
    "%PDF-1.4\n" +
    "1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n" +
    "2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n" +
    "3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/MediaBox [0 0 612 792]\n>>\nendobj\n" +
    "xref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n" +
    "0000000058 00000 n\n0000000115 00000 n\n" +
    "trailer\n<<\n/Size 4\n/Root 1 0 R\n>>\nstartxref\n196\n%%EOF" +
    `\n%% tour run ${Date.now()}\n`,   // unique bytes → avoids the sha256 duplicate-upload 409
  );
}

async function apiLogin() {
  const r1 = await fetch(`${BACKEND}/api/v1/auth/otp/request`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier: EMAIL, purpose: "LOGIN" }),
  });
  let b1 = await r1.json();
  if (r1.status !== 200) {
    const r1b = await fetch(`${BACKEND}/api/v1/auth/otp/request`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identifier: EMAIL, purpose: "REGISTER" }),
    });
    b1 = await r1b.json();
  }
  const r2 = await fetch(`${BACKEND}/api/v1/auth/otp/verify`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier: EMAIL, otp: b1.data.dev_otp }),
  });
  const b2 = await r2.json();
  return b2.data.access_token;
}

async function main() {
  const token = await apiLogin();
  const h = { Authorization: `Bearer ${token}` };
  const gstin = makeGstin("27");
  const created = await fetch(`${BACKEND}/api/v1/gst-accounts`, {
    method: "POST", headers: { ...h, "Content-Type": "application/json" },
    body: JSON.stringify({ gstin, legal_name: `Tour Demo Co ${Date.now()}`, filing_scheme: "REGULAR_MONTHLY" }),
  });
  step(0, "API: create GSTIN for this tour", `POST /gst-accounts ${gstin} -> ${created.status}`);

  const browser = await chromium.launch({ args: ["--disable-gpu", "--no-sandbox"] });
  const page = await browser.newPage();
  let shot = 0;
  const snap = async (name) => { shot += 1; const p = path.join(OUT, `${String(shot).padStart(2, "0")}-${name}.png`); await page.screenshot({ path: p, fullPage: true }); return p; };

  // ---- 1. Login screen ----
  await page.goto(`${FRONTEND}/login`);
  await page.getByTestId("login-identifier").fill(EMAIL);
  const loginShot = await snap("login-screen");
  await page.getByTestId("login-request-otp").click();
  const banner = page.getByTestId("dev-otp");
  await banner.waitFor({ state: "visible" });
  const code = (await banner.textContent()).match(/dev code:\s*(\d{6})/)[1];
  step(1, "Login screen (email-only OTP)", `GET /login 200; dev OTP echoed; screen → ${loginShot}`);
  await page.getByTestId("login-otp").fill(code);
  await page.getByTestId("login-verify").click();
  await page.waitForURL(/\/app$/, { timeout: 15000 });

  // ---- 2. Unified shell ----
  await page.getByTestId("gst-account-card").first().waitFor({ state: "visible", timeout: 10000 });
  const shellShot = await snap("shell-dashboard");
  const cardCount = await page.getByTestId("gst-account-card").count();
  step(2, "Unified shell — GSTIN dashboard", `${cardCount} GST account card(s) rendered; screen → ${shellShot}`);

  // ---- 3. Upload screen via the shell's own link ----
  await page.getByTestId("upload-link").first().click();
  await page.waitForURL(/\/app\/upload\//);
  await page.getByTestId("file-input").setInputFiles({ name: "invoice.pdf", mimeType: "application/pdf", buffer: minimalPdf() });
  const uploadShot = await snap("upload-screen");
  step(3, "Upload screen (capture source + file drop)", `URL ${page.url().replace(FRONTEND, "")}; screen → ${uploadShot}`);
  await page.getByTestId("upload-submit").click();
  const success = page.getByTestId("upload-success");
  await success.waitFor({ state: "visible", timeout: 30000 });
  const statusText = await success.textContent();
  const docId = statusText.match(/Document ID:\s*([0-9a-f-]{36})/i)[1];
  const upShot = await snap("upload-success");
  step(4, "Upload → extraction", `doc ${docId}; status text present; screen → ${upShot}`);

  // ---- 5. Review screen ----
  await page.goto(`${FRONTEND}/app`);
  await page.getByTestId("gst-account-card").first().waitFor({ state: "visible", timeout: 10000 });
  await page.goto(`${FRONTEND}/app/review/${gstin}/${FP}/${docId}`);
  await page.getByText("Review & confirm").waitFor({ state: "visible", timeout: 10000 });
  const confirmBtn = page.getByTestId("confirm-document");
  await confirmBtn.waitFor({ state: "visible" });
  const revShot = await snap("review-screen");
  const flagCount = await page.locator("text=Validation flags").count();
  step(5, "Review & confirm", `Confirm enabled=${await confirmBtn.isEnabled()}; flags banner=${flagCount}; screen → ${revShot}`);

  // ---- 6. Confirm ----
  await confirmBtn.click();
  await page.getByTestId("review-success").waitFor({ state: "visible", timeout: 10000 });
  const okShot = await snap("confirm-success");
  step(6, "Confirm → invoice written to ledger", `review-success visible; screen → ${okShot}`);

  // ---- 7. Returns output ----
  await page.getByTestId("go-to-returns").click();
  await page.waitForURL(/\/app\/returns\//);
  await page.getByTestId("download-gstr1").waitFor({ state: "visible", timeout: 10000 });
  const retShot = await snap("returns-output");
  const [d1] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-gstr1").click()]);
  const [d3] = await Promise.all([page.waitForEvent("download"), page.getByTestId("download-gstr3b").click()]);
  step(7, "Returns output — GSTR-1 + GSTR-3B download", `GSTR1=${d1.suggestedFilename()}; GSTR3B=${d3.suggestedFilename()}; screen → ${retShot}`);

  await browser.close();

  // ---- 8. API-only capabilities (no screen) ----
  const probes = [
    ["GET", `/gst-accounts/${gstin}/months/${FP}/summary`],
    ["GET", `/gst-accounts/${gstin}/months/${FP}/gstr1/export.json`],
    ["GET", `/gst-accounts/${gstin}/months/${FP}/gstr3b/export.json`],
    ["GET", `/gst-accounts/${gstin}/months/${FP}/review-queue`],
    ["GET", "/gst-accounts"],
    ["GET", "/auth/me"],
  ];
  const results = [];
  for (const [m, p] of probes) {
    const r = await fetch(BACKEND + "/api/v1" + p, { method: m, headers: h });
    results.push(`${m} ${p} -> ${r.status}`);
  }
  step(8, "Backend capabilities (API probes)", results.join(" | "));

  fs.writeFileSync(path.join(OUT, "tour-report.json"), JSON.stringify({ email: EMAIL, gstin, fp: FP, docId, steps }, null, 2));
  console.log(`\n[TOUR] report + screenshots in ${OUT}`);
}

main().catch((e) => { console.error("[TOUR FAILED]", e); process.exit(1); });
