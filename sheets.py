"""Write tables to Google Sheets via a service account (gspread)."""
import gspread
from gspread.utils import rowcol_to_a1
import numpy as np
import pandas as pd


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
