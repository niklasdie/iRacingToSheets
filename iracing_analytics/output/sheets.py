"""Write tables to Google Sheets via a service account (gspread)."""
import gspread
from gspread.utils import rowcol_to_a1
import numpy as np
import pandas as pd


# Locales whose number format uses a comma as the decimal separator. Google
# Sheets parses USER_ENTERED formulas in the spreadsheet's locale, and in those
# locales it also expects ';' (not ',') between function arguments. Keyed by the
# language part of the locale string (e.g. "de" in "de_DE").
_COMMA_DECIMAL_LANGS = frozenset({
    "de", "fr", "es", "it", "nl", "pt", "ru", "pl", "sv", "da", "fi",
    "nb", "nn", "no", "cs", "sk", "hu", "ro", "bg", "hr", "sl", "sr",
    "uk", "tr", "el", "lt", "lv", "et", "is", "ca", "eu", "gl", "af",
    "vi", "id", "be", "kk", "az", "sq", "mk", "mn",
})


def separators_for_locale(locale: str | None) -> tuple[str, str]:
    """Return (decimal_separator, argument_separator) for a Sheets locale.

    German and most continental-European locales use ',' for decimals and ';'
    between function arguments; US/English-style locales use '.' and ','.
    """
    lang = (locale or "en_US").replace("-", "_").split("_", 1)[0].lower()
    if lang in _COMMA_DECIMAL_LANGS:
        return ",", ";"
    return ".", ","


def localize_formula(value, decimal_sep: str, arg_sep: str):
    """Rewrite a canonical (English-notation) formula for the sheet's locale.

    Formulas are authored with '.' decimals and ',' between arguments. For a
    German sheet they must use ',' decimals and ';' separators instead. Only
    strings that start with '=' are touched, and never the text inside quoted
    string literals. A no-op when the locale already matches English notation,
    so plain data values pass through unchanged.
    """
    if not isinstance(value, str) or not value.startswith("="):
        return value
    if decimal_sep == "." and arg_sep == ",":
        return value
    out, in_string = [], False
    for ch in value:
        if ch == '"':
            in_string = not in_string
            out.append(ch)
        elif in_string:
            out.append(ch)
        elif ch == ".":
            out.append(decimal_sep)
        elif ch == ",":
            out.append(arg_sep)
        else:
            out.append(ch)
    return "".join(out)


def _clean(value):
    """Make a value safe for the Sheets API (no NaN / numpy scalars)."""
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def df_to_values(df: pd.DataFrame) -> list:
    """DataFrame -> list-of-lists (header row + data) ready for gspread."""
    header = [str(c) for c in df.columns]
    rows = [[_clean(v) for v in row] for row in df.itertuples(index=False, name=None)]
    return [header] + rows


class SheetWriter:
    def __init__(self, creds_path: str):
        self._gc = gspread.service_account(filename=creds_path)

    @staticmethod
    def _formula_separators(sh) -> tuple[str, str]:
        """Decimal + argument separators for this spreadsheet's locale."""
        try:
            locale = sh.locale
        except (KeyError, AttributeError):
            locale = None
        return separators_for_locale(locale)

    def open_or_create(self, sheet_id: str | None, title: str, share_email: str | None):
        if sheet_id:
            return self._gc.open_by_key(sheet_id)
        sh = self._gc.create(title)
        if share_email:
            sh.share(share_email, perm_type="user", role="writer", notify=False)
        return sh

    def write_tab(self, sh, name: str, values: list):
        ncols = max((len(r) for r in values), default=1)
        try:
            ws = sh.worksheet(name)
            ws.clear()
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=name, rows=max(len(values) + 5, 20), cols=ncols + 2)

        if not values:
            return ws

        decimal_sep, arg_sep = self._formula_separators(sh)
        values = [[localize_formula(v, decimal_sep, arg_sep) for v in row] for row in values]
        ws.update(values=values, range_name="A1", value_input_option="USER_ENTERED")
        ws.freeze(rows=1)
        ws.format(f"A1:{rowcol_to_a1(1, ncols)}", {"textFormat": {"bold": True}})
        return ws

    def remove_default_sheet(self, sh):
        """Drop the auto-created 'Sheet1' on freshly created spreadsheets."""
        try:
            ws = sh.worksheet("Sheet1")
            if len(sh.worksheets()) > 1:
                sh.del_worksheet(ws)
        except gspread.WorksheetNotFound:
            pass

    def highlight_inputs(self, sh, tab_name: str, ranges: list):
        """Tint the editable input cells so it's obvious what to change."""
        try:
            ws = sh.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            return
        fmt = {"backgroundColor": {"red": 1.0, "green": 0.95, "blue": 0.6},
               "textFormat": {"bold": True}}
        for rng in ranges:
            ws.format(rng, fmt)
