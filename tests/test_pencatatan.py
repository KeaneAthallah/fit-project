"""The tanggal pencatatan register -- the IDX listing dates the
results grid joins onto every company-year row.

The register is a workbook of kode, nama, tanggal. The join has
to survive the ways the same company is spelled on each side: the
database stores "AALI Astra Agro Lestari Tbk", the register prints
"Astra Agro Lestari Tbk." in a column of its own, and the date may
be a real date cell or the "09 Des 1997" string the IDX export
produces.
"""
from datetime import date

import openpyxl
import pytest

from app.dashboard.pencatatan import Pencatatan, load_pencatatan


def _workbook(path, rows, header=("No", "Kode", "Nama Perusahaan", "Tanggal Pencatatan")):
    wb = openpyxl.Workbook()
    ws = wb.active
    if header is not None:
        ws.append(list(header))
    for row in rows:
        ws.append(list(row))
    wb.save(path)


def test_reads_the_register_layout(tmp_path):
    """The real file's shape: a No column, then kode, name and
    the listing date exactly as the IDX prints it -- day,
    Indonesian month abbreviation, year."""
    path = tmp_path / "tanggal pencatatan.xlsx"
    _workbook(path, [
        [1, "AALI", "Astra Agro Lestari Tbk.", "09 Des 1997"],
        [2, "AMMS", "Agung Menjangan Mas Tbk.", "04 Agt 2022"],
        [3, "ASHA", "Cilacap Samudera Fishing Indus", "27 Mei 2022"],
    ])
    register = load_pencatatan(path)

    assert register.get("AALI Astra Agro Lestari Tbk") == date(1997, 12, 9)
    assert register.get("AMMS Agung Menjangan Mas Tbk") == date(2022, 8, 4)
    assert register.get("ASHA Cilacap Samudera Fishing Indus") == date(2022, 5, 27)


def test_matches_the_name_when_the_ticker_is_missing(tmp_path):
    """A stored company that lost its ticker still lands on its
    row: the name alone is a key, not only kode-plus-name."""
    path = tmp_path / "register.xlsx"
    _workbook(path, [[1, "AALI", "Astra Agro Lestari Tbk.", "09 Des 1997"]])
    register = load_pencatatan(path)

    assert register.get("Astra Agro Lestari Tbk") == date(1997, 12, 9)


def test_ignores_spelling_that_carries_no_identity(tmp_path):
    """PT prefixes, Tbk suffixes and punctuation must not split
    one company into two keys."""
    path = tmp_path / "register.xlsx"
    _workbook(path, [[1, "AALI", "PT Astra Agro Lestari Tbk.", "09 Des 1997"]])
    register = load_pencatatan(path)

    assert register.get("aali astra agro lestari") == date(1997, 12, 9)
    assert register.get("PT AALI Astra Agro Lestari Tbk") == date(1997, 12, 9)


def test_accepts_date_cells_and_other_written_formats(tmp_path):
    """A real date cell, the European numeric form and the ISO
    form are all the same day."""
    path = tmp_path / "register.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Kode", "Nama", "Tanggal"])
    ws.append(["AAA", "PT Alpha Tbk", date(2001, 3, 15)])
    ws.append(["BBB", "PT Beta Tbk", "15/03/2002"])
    ws.append(["CCC", "PT Gamma Tbk", "2003-03-16"])
    wb.save(path)
    register = load_pencatatan(path)

    assert register.get("AAA Alpha") == date(2001, 3, 15)
    assert register.get("BBB Beta") == date(2002, 3, 15)
    assert register.get("CCC Gamma") == date(2003, 3, 16)


def test_skips_rows_without_a_usable_date(tmp_path):
    """The header row and a malformed entry are not companies;
    the loader must not die on them, and must not index them."""
    path = tmp_path / "register.xlsx"
    _workbook(path, [
        # A header row holds no parseable date, so it is skipped
        # by the same rule as a bad entry -- no special-casing.
        [1, "AAA", "PT Alpha Tbk", "09 Des 1997"],
        [2, "BBB", "PT Beta Tbk", "belum tercatat"],
        [3, "CCC", None, "09 Des 1997"],
    ])
    register = load_pencatatan(path)

    assert register.get("AAA Alpha") == date(1997, 12, 9)
    assert register.get("BBB Beta") is None
    assert register.get("CCC") is None


def test_rereads_when_the_file_changes(tmp_path):
    """The register is cached by mtime, so an edit to the
    workbook shows up without a server restart."""
    path = tmp_path / "register.xlsx"
    _workbook(path, [[1, "AAA", "PT Alpha Tbk", "09 Des 1997"]])
    assert load_pencatatan(path).get("AAA Alpha") == date(1997, 12, 9)

    _workbook(path, [[1, "AAA", "PT Alpha Tbk", "09 Des 1998"]])
    # Force a new mtime: a rewrite within the same clock tick
    # would otherwise be served from the cache.
    import os
    import time

    stamp = time.time() + 5
    os.utime(path, (stamp, stamp))
    assert load_pencatatan(path).get("AAA Alpha") == date(1998, 12, 9)


def test_a_missing_register_is_an_error_not_an_empty_one(tmp_path):
    """An unreadable register must fail loudly: silently
    returning an empty mapping would make the "listed before"
    filter hide every company, which reads as a broken table
    rather than as a missing file."""
    with pytest.raises(FileNotFoundError):
        load_pencatatan(tmp_path / "tidak-ada.xlsx")


def test_a_register_without_any_date_is_an_error(tmp_path):
    """A workbook that parses but yields no listing date is as
    broken as a missing one, for the same reason."""
    path = tmp_path / "register.xlsx"
    _workbook(path, [[1, "AAA", "PT Alpha Tbk", "belum tercatat"]])
    with pytest.raises(ValueError):
        load_pencatatan(path)


def test_pencatatan_get_handles_the_absent_company():
    assert Pencatatan().get(None) is None
    assert Pencatatan().get("") is None
