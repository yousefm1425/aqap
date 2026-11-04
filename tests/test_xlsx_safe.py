"""حماية التصدير من حقن المعادلات: نص المستخدم الذي يبدأ بـ = يبقى نصاً، ومعادلات المنصة تبقى معادلات."""
import io

from openpyxl import Workbook, load_workbook

from app.xlsx_safe import csv_cell, csv_uncell, harden, trusted_formula


def test_trusted_formulas_kept():
    for f in ['=IF(COUNT(B2:B9)=0,"",SUM(B2:B9))', "=ROWS(A2:A9)", '=IFERROR(COUNTIF(C2:C9,"نعم")/ROWS(C2:C9),"")',
              "='نموذج 1'!D7", '=IF(OR(COUNT(B2)=0,SUM(C2)=0),"",SUM(B2)/SUM(C2))']:
        assert trusted_formula(f), f


def test_malicious_formulas_rejected():
    for f in ['=HYPERLINK("http://evil","اضغط")', "=cmd|' /C calc'!A0", '=WEBSERVICE("http://x")', "=IMPORTXML(A1)",
              "=[book.xlsx]Sheet1!A1", '=SUM(1)+HYPERLINK("x")']:
        assert not trusted_formula(f), f


def test_harden_workbook_roundtrip():
    wb = Workbook()
    ws = wb.active
    ws["A1"] = '=HYPERLINK("http://evil","افتح")'        # نص كتبه مستخدم
    ws["A2"] = "=SUM(B1:B3)"                              # معادلة المنصة
    ws["A3"] = "-عنوان عادي"
    assert harden(wb) == 1
    buf = io.BytesIO()
    wb.save(buf)
    ws2 = load_workbook(io.BytesIO(buf.getvalue())).active
    assert ws2["A1"].data_type == "s" and ws2["A1"].value == '=HYPERLINK("http://evil","افتح")'
    assert ws2["A2"].data_type == "f"
    assert ws2["A3"].value == "-عنوان عادي"


def test_csv_cell():
    assert csv_cell("=1+2") == "'=1+2" and csv_cell("@SUM(A1)") == "'@SUM(A1)" and csv_cell("عادي") == "عادي"
    assert csv_uncell(csv_cell("=1+2")) == "=1+2" and csv_uncell("'عادي") == "'عادي"
