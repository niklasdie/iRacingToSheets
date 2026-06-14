"""Reader for iRacing `.ibt` telemetry files (local iRacing SDK output).

This is the sim's *local telemetry* API — a different, file-based API from the
web `/data` API, and crucially NOT affected by the OAuth client-ID pause. A
`.ibt` file is written per session to `Documents/iRacing/telemetry/` when
telemetry logging is enabled; it can be parsed on any OS (parsing is plain file
I/O), so you capture it on the Windows sim box and analyse it here.

Each file holds:
  • a SessionInfo YAML block — drivers, results, lap times, track/car, incidents
  • per-tick telemetry channels — Speed, Throttle, Brake, Lap, LapDistPct, ...

`pyirsdk`'s IBT class reads the telemetry channels but does not expose the
SessionInfo block, so we read that ourselves from the header offsets.
"""
import yaml
from irsdk import IBT, CustomYamlSafeLoader


class IBTSession:
    def __init__(self, path: str):
        self._ibt = IBT()
        self._ibt.open(path)
        self.path = path
        self.session_info: dict = self._read_session_info()
        self.record_count: int = self._ibt._disk_header.session_record_count

    # --- telemetry channels -------------------------------------------------

    @property
    def var_names(self) -> list:
        return self._ibt.var_headers_names or []

    def channel(self, name: str) -> list:
        """All samples for one telemetry channel ([] if the channel is absent)."""
        if name not in (self._ibt._var_headers_dict or {}):
            return []
        return self._ibt.get_all(name) or []

    # --- session metadata ---------------------------------------------------

    @property
    def player_car_idx(self):
        return (self.session_info.get("DriverInfo") or {}).get("DriverCarIdx")

    def close(self) -> None:
        self._ibt.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- internals ----------------------------------------------------------

    def _read_session_info(self) -> dict:
        h = self._ibt._header
        raw = self._ibt._shared_mem[
            h.session_info_offset : h.session_info_offset + h.session_info_len
        ].rstrip(b"\x00")
        # iRacing writes UTF-8 (sometimes with a BOM) or cp1252; try both.
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
        return yaml.load(text, Loader=CustomYamlSafeLoader) or {}
