from datetime import date

from app.services.returns.deadline import compute_due_dates


def test_compute_due_dates_regular():
    # Regular Monthly: April 2026
    # GSTR-1: 11th May 2026, 3B: 20th May 2026
    dates = compute_due_dates("27ABCDE1234F1Z5", "042026", "REGULAR_MONTHLY")
    assert dates["gstr1_due_date"] == date(2026, 5, 11)
    assert dates["gstr3b_due_date"] == date(2026, 5, 20)
    assert dates["gstr2b_due_date"] == date(2026, 5, 14)
    assert dates["iff_eligible"] is False

def test_compute_due_dates_qrmp_cat1():
    # QRMP: April 2026 (Month 1 of Q1)
    # GSTR-1: 13th May 2026, IFF: 13th May 2026
    # 3B: 22nd July 2026 (Category 1 State - Maharashtra '27')
    dates = compute_due_dates("27ABCDE1234F1Z5", "042026", "QRMP")
    assert dates["gstr1_due_date"] == date(2026, 5, 13)
    assert dates["iff_due_date"] == date(2026, 5, 13)
    assert dates["iff_eligible"] is True
    assert dates["gstr3b_due_date"] == date(2026, 7, 22)
    assert dates["gstr2b_due_date"] == date(2026, 5, 14)

def test_compute_due_dates_qrmp_cat2():
    # QRMP: April 2026 (Month 1 of Q1)
    # Category 2 State - e.g. Delhi '07'
    # 3B: 24th July 2026
    dates = compute_due_dates("07ABCDE1234F1Z5", "042026", "QRMP")
    assert dates["gstr3b_due_date"] == date(2026, 7, 24)

def test_compute_due_dates_composition():
    # Composition: April 2026
    # CMP-08: 18th July 2026 (for Q1)
    # GSTR-4: None for April
    dates = compute_due_dates("27ABCDE1234F1Z5", "042026", "COMPOSITION")
    assert dates["cmp08_due_date"] == date(2026, 7, 18)
    assert dates["gstr4_due_date"] is None

    # March 2027
    # GSTR-4: 30th April 2027
    dates = compute_due_dates("27ABCDE1234F1Z5", "032027", "COMPOSITION")
    assert dates["gstr4_due_date"] == date(2027, 4, 30)
