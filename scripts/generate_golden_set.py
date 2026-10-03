import json
import random
from backend.tests.gstin_fixtures import make_gstin

# We need >= 50% PHOTO/WHATSAPP
# Explicitly set sources: 6 PHOTO, 6 WHATSAPP, 4 PDF_SCAN, 4 DIGITAL = 12/20 = 60%
sources = ["PHOTO"] * 6 + ["WHATSAPP"] * 6 + ["PDF_SCAN"] * 4 + ["DIGITAL"] * 4
random.shuffle(sources)

def generate_invoice(doc_id, source):
    supplier_gstin = make_gstin()
    buyer_gstin = make_gstin()
    
    return {
        "doc_id": doc_id,
        "capture_source": source,
        "fields": {
            "supplier_gstin": supplier_gstin,
            "buyer_gstin": buyer_gstin,
            "invoice_no": f"INV-{random.randint(1000, 9999)}",
            "invoice_date": f"2026-09-{random.randint(10, 28):02d}",
            "place_of_supply": "27",
            "is_inter_state": False,
            "rchrg": False,
            "inv_typ": "R",
            "taxable_value_paise": 1000000,
            "total_value_paise": 1180000,
            "cgst_paise": 90000,
            "sgst_paise": 90000,
            "igst_paise": 0,
            "cess_paise": 0
        }
    }

for i in range(1, 21):
    doc_id = f"INV-{i:04d}"
    invoice = generate_invoice(doc_id, sources[i-1])
    with open(f"D:/gst_filing_app/extraction/golden_set/ground_truth/{doc_id}.json", "w") as f:
        json.dump(invoice, f, indent=2)
