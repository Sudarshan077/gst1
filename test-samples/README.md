# Test Samples — GST Filing App

Drop-in fixtures for exercising the **upload → extract → review → confirm → returns** path, plus failure cases. Upload them through the UI (`/app/upload/{gstin}/{fp}`) or the API (`POST /api/v1/gst-accounts/{gstin}/months/{fp}/documents`).

| File | Type | Purpose | Expected result |
|---|---|---|---|
| `invoice_b2b_intrastate.pdf` | valid PDF | B2B intra-state sale (CGST+SGST) | extracts cleanly; supply_type INTRA |
| `invoice_b2b_interstate.pdf` | valid PDF | B2B inter-state sale (IGST) | extracts cleanly; supply_type INTER |
| `real_online_gst_doc.pdf` | valid PDF (real-world) | a real-format GST document for the golden set | extracts; may raise non-blocking `FLAG`s |
| `corrupted_invoice.pdf` | broken bytes | preprocess/blur/parse failure path | upload may store; extraction → `FAILED` (`re-upload a clearer image`) |
| `not_a_pdf.txt` | wrong type | MIME/format rejection | upload rejected or extraction `FAILED` (unsupported bytes) |

## Rules when using these

- **Every run needs unique bytes.** The backend dedupes by sha256 per `(gstin, fp)` and returns `409` for an identical re-upload. Append a comment to the PDF, e.g. `%% tour run <timestamp>` (see `scripts/app_tour.cjs`).
- **The `fp` must be a valid `MMYYYY`** matching `^(0[1-9]|1[0-2])(20\d{2})$` — `092026` = Sep 2026.
- **The GSTIN must be checksum-valid** and you must have FILER/ADMIN on it. Generate with `make_gstin()` (`scripts/seed_demo.py` or `backend/app/core/gstin.py`); never hand-type one.
- These are dev/test fixtures only — do not treat as real taxpayer data.

## Adding your own fixtures

Put real (anonymised) invoices in the golden set instead — `extraction/golden_set/` — and keep ground-truth JSON alongside. Anonymise GSTIN/PAN first (valid-format synthetic identifiers that pass checksum).
