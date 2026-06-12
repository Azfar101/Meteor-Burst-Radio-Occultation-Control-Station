"""
Auto-fetch COSMIC-2 ionPrf data from the UCAR CDAAC archive.

For a chosen [start, end] date range, downloads one gzipped tar archive
per day from

    {BASE_URL}/{YYYY}/{DOY}/ionPrf_prov1_{YYYY}_{DOY}.tar.gz

extracts the individual ionPrf NetCDF profiles, and runs them through the
exact same E-region peak-gradient + meteor-spike pipeline used for manual
imports (``cosmic2_loader``).

The work happens in a background thread with live progress reporting;
processed profiles are streamed into the shared ``Ionosphere`` model day
by day, so the map can update while a long range is still downloading.
Only stdlib networking (``urllib``) and archive handling (``tarfile``)
are used — no extra dependencies.
"""

import datetime
import io
import os
import shutil
import tarfile
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

from . import cosmic2_loader

BASE_URL = ("https://data.cosmic.ucar.edu/gnss-ro/cosmic2/"
            "provisional/spaceWeather/level2")
CACHE_DIR = Path(__file__).resolve().parent / "data" / "cache"
MAX_DAYS = 31
USER_AGENT = "MBC-GroundControl/1.1 (+cosmic2-auto-fetch)"
DOWNLOAD_TIMEOUT_S = 180
CHUNK = 256 * 1024


class FetchError(Exception):
    """User-facing problem (bad range, already running, …)."""


class _DayUnavailable(Exception):
    """The archive has no file for this day (HTTP 404) — skipped, not fatal."""


class _Cancelled(Exception):
    """Raised internally to unwind the worker when the user cancels."""


def _now_iso():
    return datetime.datetime.utcnow().isoformat() + "Z"


def _parse_date(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        raise FetchError(f"invalid date: {s!r} (expected YYYY-MM-DD)")


def _day_filename(d):
    return f"ionPrf_prov1_{d.year}_{d.timetuple().tm_yday:03d}.tar.gz"


def _day_url(d):
    doy = d.timetuple().tm_yday
    return f"{BASE_URL}/{d.year}/{doy:03d}/{_day_filename(d)}"


# ── background job ────────────────────────────────────────────────────────────

class _FetchJob:
    def __init__(self, iono, start, end):
        self.iono = iono
        self.days = [start + datetime.timedelta(days=i)
                     for i in range((end - start).days + 1)]
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self.state = {
            "running": True,
            "phase": "queued",          # queued|downloading|processing|done|cancelled|error
            "start": start.isoformat(),
            "end": end.isoformat(),
            "total_days": len(self.days),
            "completed_days": 0,
            "current": None,
            "current_doy": None,
            "message": "Queued…",
            "pct": 0.0,
            "days": [{
                "date": d.isoformat(),
                "doy": d.timetuple().tm_yday,
                "status": "pending",    # pending|downloading|processing|done|unavailable|error
                "imported": 0,
                "skipped": 0,
                "error": None,
            } for d in self.days],
            "imported": 0,
            "duplicates": 0,
            "skipped_total": 0,
            "total_profiles": len(iono.profiles),
            "time_min": None,
            "time_max": None,
            "error": None,
            "cancelled": False,
            "started_at": _now_iso(),
            "finished_at": None,
        }

    # ── progress helpers (all writes go through the lock) ──
    def cancel(self):
        self._cancel.set()

    def snapshot(self):
        with self._lock:
            s = dict(self.state)
            s["days"] = [dict(x) for x in self.state["days"]]
            return s

    def _update(self, **kw):
        with self._lock:
            self.state.update(kw)

    def _update_day(self, i, **kw):
        with self._lock:
            self.state["days"][i].update(kw)

    def _set_pct(self, day_idx, day_frac):
        """Overall progress: completed days + fractional progress of the current one."""
        with self._lock:
            self.state["pct"] = round(
                100.0 * (day_idx + max(0.0, min(1.0, day_frac))) / len(self.days), 1)

    def _check_cancel(self):
        if self._cancel.is_set():
            raise _Cancelled()

    # ── main loop ──
    def run(self):
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            for i, d in enumerate(self.days):
                self._check_cancel()
                doy = d.timetuple().tm_yday
                label = f"Day {i + 1}/{len(self.days)} · {d.isoformat()}"
                self._update(current=d.isoformat(), current_doy=doy,
                             phase="downloading", message=f"{label}: downloading…")
                self._update_day(i, status="downloading")
                try:
                    data = self._download_day(d, i, label)
                except _DayUnavailable:
                    self._update_day(i, status="unavailable")
                    self._finish_day(i)
                    continue
                except _Cancelled:
                    raise
                except Exception as e:  # noqa: BLE001 — record and carry on
                    self._update_day(i, status="error", error=str(e))
                    self._finish_day(i)
                    continue

                self._update(phase="processing",
                             message=f"{label}: processing profiles…")
                self._update_day(i, status="processing")
                try:
                    added, dups, skipped = self._process_day(data, i, label)
                except _Cancelled:
                    raise
                except Exception as e:  # noqa: BLE001
                    self._update_day(i, status="error", error=str(e))
                    self._finish_day(i)
                    continue

                self._update_day(i, status="done", imported=added, skipped=skipped)
                with self._lock:
                    self.state["imported"] += added
                    self.state["duplicates"] += dups
                    self.state["skipped_total"] += skipped
                self._finish_day(i)

            self._finalize(cancelled=False)
        except _Cancelled:
            self._finalize(cancelled=True)
        except Exception as e:  # noqa: BLE001 — surface unexpected failures
            self._update(running=False, phase="error", error=str(e),
                         message=f"Failed: {e}", finished_at=_now_iso())

    def _finish_day(self, i):
        tr = self.iono.time_range()
        with self._lock:
            self.state["completed_days"] = i + 1
            self.state["pct"] = round(100.0 * (i + 1) / len(self.days), 1)
            self.state["total_profiles"] = len(self.iono.profiles)
            if tr:
                self.state["time_min"] = tr[0].isoformat() + "Z"
                self.state["time_max"] = tr[1].isoformat() + "Z"

    def _finalize(self, cancelled):
        done = self.snapshot()
        msg = ("Cancelled — kept profiles fetched so far."
               if cancelled else
               f"Complete · {done['imported']} new profile(s) from "
               f"{done['completed_days']} day(s).")
        self._update(running=False, cancelled=cancelled,
                     phase="cancelled" if cancelled else "done",
                     current=None, current_doy=None, pct=100.0,
                     message=msg, finished_at=_now_iso())

    # ── per-day work ──
    def _download_day(self, d, i, label):
        cache_file = CACHE_DIR / _day_filename(d)
        if cache_file.is_file() and cache_file.stat().st_size > 0:
            self._update(message=f"{label}: cached")
            return cache_file.read_bytes()

        req = urllib.request.Request(_day_url(d), headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_S) as r:
                total = int(r.headers.get("Content-Length") or 0)
                buf = io.BytesIO()
                got = 0
                while True:
                    self._check_cancel()
                    chunk = r.read(CHUNK)
                    if not chunk:
                        break
                    buf.write(chunk)
                    got += len(chunk)
                    if total:
                        self._set_pct(i, 0.5 * got / total)
                        self._update(message=(f"{label}: downloading "
                                              f"{got >> 20}/{total >> 20} MB"))
                data = buf.getvalue()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise _DayUnavailable()
            raise RuntimeError(f"HTTP {e.code} {e.reason}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"network error: {e.reason}")

        tmp = cache_file.with_name(cache_file.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(cache_file)
        return data

    def _process_day(self, data, i, label):
        tmpdir = Path(tempfile.mkdtemp(prefix="cosmic2_"))
        profiles = []
        n_skipped = 0
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
                members = [m for m in tf.getmembers() if m.isfile()]
                n = len(members)
                for j, m in enumerate(members):
                    self._check_cancel()
                    base = os.path.basename(m.name)
                    if not base:
                        continue
                    src = tf.extractfile(m)
                    if src is None:
                        continue
                    dest = tmpdir / base
                    with src:
                        dest.write_bytes(src.read())
                    try:
                        prof, _reason = cosmic2_loader.process_file(dest)
                    except Exception:  # noqa: BLE001 — malformed member, skip it
                        prof = None
                    if prof:
                        profiles.append(prof)
                    else:
                        n_skipped += 1
                    dest.unlink(missing_ok=True)
                    if j % 100 == 0 or j == n - 1:
                        self._set_pct(i, 0.5 + 0.5 * (j + 1) / max(1, n))
                        self._update_day(i, imported=len(profiles), skipped=n_skipped)
                        self._update(message=(f"{label}: processed {j + 1}/{n} files · "
                                              f"{len(profiles)} profiles"))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        added = self.iono.add_profiles(profiles)
        return added, len(profiles) - added, n_skipped


# ── module-level job manager (single-user app → one job at a time) ────────────

_current = None
_manager_lock = threading.Lock()

_IDLE = {
    "running": False, "phase": "idle", "message": "No fetch has been started.",
    "start": None, "end": None, "total_days": 0, "completed_days": 0,
    "current": None, "current_doy": None, "pct": 0.0, "days": [],
    "imported": 0, "duplicates": 0, "skipped_total": 0, "total_profiles": None,
    "time_min": None, "time_max": None, "error": None, "cancelled": False,
}


def start(iono, start_str, end_str):
    """Validate the range and launch a background fetch. Returns the first snapshot."""
    start_d = _parse_date(start_str)
    end_d = _parse_date(end_str)
    if end_d < start_d:
        raise FetchError("end date is before start date")
    today = datetime.datetime.utcnow().date()
    if start_d > today:
        raise FetchError("start date is in the future")
    ndays = (end_d - start_d).days + 1
    if ndays > MAX_DAYS:
        raise FetchError(f"range too large: {ndays} days (maximum is {MAX_DAYS})")

    global _current
    with _manager_lock:
        if _current is not None and _current.state["running"]:
            raise FetchError("a fetch is already running")
        job = _FetchJob(iono, start_d, end_d)
        _current = job
    threading.Thread(target=job.run, daemon=True).start()
    return job.snapshot()


def status():
    with _manager_lock:
        job = _current
    return job.snapshot() if job is not None else dict(_IDLE)


def cancel():
    with _manager_lock:
        job = _current
    if job is None or not job.state["running"]:
        raise FetchError("no fetch is running")
    job.cancel()
    return job.snapshot()
