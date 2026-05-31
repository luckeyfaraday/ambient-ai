from __future__ import annotations

import ctypes
import os
import platform
import shutil
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from hashlib import sha1
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .events import AmbientEvent
from .redaction import redact_command  # re-exported for backward compatibility


class Collector:
    source = "unknown"

    def collect(self) -> list[AmbientEvent]:
        return []


_SKIP_SCHEMES = ("about:", "moz-extension:", "chrome:", "chrome-extension:", "file:")
_CHROME_EPOCH_OFFSET_SECONDS = 11_644_473_600
# Auth/SSO hosts and path segments that are pure navigational plumbing, never user
# intent. Kept deliberately narrow: search queries and content pages are left for
# Hermes to judge, not dropped here.
_NOISE_HOST_SUFFIXES = (
    "accounts.google.com",
    "login.microsoftonline.com",
    "login.live.com",
    "oauth2.googleapis.com",
)
_NOISE_HOST_KEYWORDS = ("auth", "login", "oauth", "sso")
_NOISE_PATH_SEGMENTS = frozenset({"oauth", "oauth2", "sso"})
_CHROMIUM_BROWSERS = {"chrome", "chromium", "edge", "brave", "vivaldi", "opera"}


class BrowserCollector(Collector):
    source = "browser"

    def __init__(self, since_minutes: int = 60, browser: str | None = None):
        self.since_minutes = since_minutes
        self.browser = browser

    def collect(self) -> list[AmbientEvent]:
        browser = self.browser or self._choose_browser()
        if browser == "firefox":
            return self._collect_firefox()
        if browser in _CHROMIUM_BROWSERS:
            return self._collect_chrome(browser)
        return []

    def _choose_browser(self) -> str | None:
        return self._detect_default_browser() or self._detect_by_recency()

    def _detect_default_browser(self) -> str | None:
        for cmd in (
            ["xdg-settings", "get", "default-web-browser"],
            ["xdg-mime", "query", "default", "x-scheme-handler/https"],
        ):
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            except (OSError, subprocess.SubprocessError):
                continue
            if result.returncode != 0:
                continue
            family = self._family_from_desktop(result.stdout.strip())
            if family:
                return family
        return None

    @staticmethod
    def _family_from_desktop(desktop: str) -> str | None:
        name = desktop.lower()
        if "firefox" in name or "librewolf" in name or "waterfox" in name:
            return "firefox"
        if "brave" in name:
            return "brave"
        if "vivaldi" in name:
            return "vivaldi"
        if "opera" in name:
            return "opera"
        if "edge" in name:
            return "edge"
        if "chromium" in name:
            return "chromium"
        if "chrome" in name:
            return "chrome"
        return None

    def _detect_by_recency(self) -> str | None:
        firefox_mtime = self._mtime_or_none(self._find_firefox_profile(), "places.sqlite")
        chromium = self._find_chrome_history_with_browser()
        chromium_mtime = self._mtime_or_none(chromium[1]) if chromium else None
        if firefox_mtime is None and chromium_mtime is None:
            return None
        if chromium_mtime is None:
            return "firefox"
        if firefox_mtime is None:
            return chromium[0] if chromium else None
        return "firefox" if firefox_mtime >= chromium_mtime else chromium[0]

    @staticmethod
    def _mtime_or_none(path: Path | None, child: str | None = None) -> float | None:
        if path is None:
            return None
        target = path / child if child else path
        try:
            return target.stat().st_mtime
        except OSError:
            return None

    def _collect_firefox(self) -> list[AmbientEvent]:
        profile = self._find_firefox_profile()
        if not profile:
            return []
        db_path = profile / "places.sqlite"
        if not db_path.exists():
            return []
        cutoff_us = int(
            (datetime.now(timezone.utc).timestamp() - self.since_minutes * 60)
            * 1_000_000
        )
        try:
            with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)) as conn:
                conn.row_factory = sqlite3.Row
                rows = [
                    {
                        "url": row["url"],
                        "title": row["title"],
                        "occurred_at": self._firefox_time_iso(row["visit_date"]),
                    }
                    for row in conn.execute(
                        """
                        SELECT p.url, p.title, v.visit_date
                        FROM moz_historyvisits v
                        JOIN moz_places p ON v.place_id = p.id
                        WHERE v.visit_date > ?
                        ORDER BY v.visit_date DESC
                        LIMIT 50
                        """,
                        (cutoff_us,),
                    ).fetchall()
                ]
        except (sqlite3.Error, OSError):
            return []
        return self._history_events(rows)

    def _collect_chrome(self, browser: str = "chrome") -> list[AmbientEvent]:
        db_path = self._find_chrome_history(browser)
        if not db_path or not db_path.exists():
            return []
        cutoff_chrome_us = int(
            (
                datetime.now(timezone.utc).timestamp()
                + _CHROME_EPOCH_OFFSET_SECONDS
                - self.since_minutes * 60
            )
            * 1_000_000
        )
        try:
            with tempfile.TemporaryDirectory(prefix="ambient-ai-chrome-history-") as tmp:
                history_copy = copy_sqlite_database(db_path, Path(tmp) / "History")
                with closing(sqlite3.connect(history_copy, timeout=2)) as conn:
                    conn.row_factory = sqlite3.Row
                    rows = [
                        {
                            "url": row["url"],
                            "title": row["title"],
                            "occurred_at": self._chrome_time_iso(row["last_visit_time"]),
                        }
                        for row in conn.execute(
                            """
                            SELECT url, title, last_visit_time
                            FROM urls
                            WHERE last_visit_time > ?
                            ORDER BY last_visit_time DESC
                            LIMIT 50
                            """,
                            (cutoff_chrome_us,),
                        ).fetchall()
                    ]
        except (sqlite3.Error, OSError):
            return []
        return self._history_events(rows)

    @staticmethod
    def _firefox_time_iso(visit_date_us: int) -> str:
        return datetime.fromtimestamp(visit_date_us / 1_000_000, timezone.utc).isoformat()

    @staticmethod
    def _chrome_time_iso(last_visit_time_us: int) -> str:
        timestamp = (last_visit_time_us / 1_000_000) - _CHROME_EPOCH_OFFSET_SECONDS
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()

    def _history_events(self, rows: list[dict[str, object]]) -> list[AmbientEvent]:
        now = datetime.now(timezone.utc).isoformat()
        events: list[AmbientEvent] = []
        for row in rows:
            url = sanitize_browser_url(str(row["url"] or ""))
            title = str(row["title"] or "")
            if not title or not url:
                continue
            if any(url.startswith(s) for s in _SKIP_SCHEMES):
                continue
            if is_low_signal_url(url):
                continue
            is_youtube = "youtube.com/watch" in url or "youtu.be/" in url
            occurred_at = row.get("occurred_at")
            events.append(
                AmbientEvent(
                    source=self.source,
                    kind="youtube_visit" if is_youtube else "history",
                    title=title,
                    url=url,
                    occurred_at=str(occurred_at or now),
                )
            )
        return events

    def _find_firefox_profile(self) -> Path | None:
        firefox_dir = Path.home() / ".mozilla" / "firefox"
        if not firefox_dir.exists():
            return None
        candidates = [
            p for p in firefox_dir.glob("*.default*")
            if (p / "places.sqlite").exists()
        ]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        best = None
        best_mtime = 0.0
        for p in candidates:
            mtime = (p / "places.sqlite").stat().st_mtime
            if mtime > best_mtime:
                best_mtime = mtime
                best = p
        return best

    def _find_chrome_history(self, browser: str | None = None) -> Path | None:
        candidates = [path for _, path in self._chrome_history_candidates(browser)]
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_mtime)

    def _find_chrome_history_with_browser(self) -> tuple[str, Path] | None:
        candidates = self._chrome_history_candidates()
        if not candidates:
            return None
        return max(candidates, key=lambda candidate: candidate[1].stat().st_mtime)

    def _chrome_history_candidates(
        self,
        browser: str | None = None,
    ) -> list[tuple[str, Path]]:
        return [
            (root_browser, path)
            for root_browser, root in self._chrome_roots_with_browser(browser)
            for path in [root / "History", *root.glob("*/History")]
            if path.exists()
        ]

    def _chrome_roots(self, browser: str | None = None) -> list[Path]:
        return [root for _, root in self._chrome_roots_with_browser(browser)]

    def _chrome_roots_with_browser(
        self,
        browser: str | None = None,
    ) -> list[tuple[str, Path]]:
        home = Path.home()
        roots_by_browser = {
            "chrome": [
                home / ".config" / "google-chrome",
                home / "Library" / "Application Support" / "Google" / "Chrome",
            ],
            "chromium": [
                home / ".config" / "chromium",
                home / "Library" / "Application Support" / "Chromium",
            ],
            "edge": [
                home / ".config" / "microsoft-edge",
                home / "Library" / "Application Support" / "Microsoft Edge",
            ],
            "brave": [
                home / ".config" / "BraveSoftware" / "Brave-Browser",
                home
                / "Library"
                / "Application Support"
                / "BraveSoftware"
                / "Brave-Browser",
            ],
            "vivaldi": [
                home / ".config" / "vivaldi",
                home / "Library" / "Application Support" / "Vivaldi",
            ],
            "opera": [
                home / ".config" / "opera",
                home / "Library" / "Application Support" / "com.operasoftware.Opera",
            ],
        }
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            roots_by_browser["chrome"].append(
                Path(local_app_data) / "Google" / "Chrome" / "User Data"
            )
            roots_by_browser["chromium"].append(
                Path(local_app_data) / "Chromium" / "User Data"
            )
            roots_by_browser["edge"].append(
                Path(local_app_data) / "Microsoft" / "Edge" / "User Data"
            )
            roots_by_browser["brave"].append(
                Path(local_app_data) / "BraveSoftware" / "Brave-Browser" / "User Data"
            )
            roots_by_browser["vivaldi"].append(
                Path(local_app_data) / "Vivaldi" / "User Data"
            )
        app_data = os.environ.get("APPDATA")
        if app_data:
            roots_by_browser["opera"].append(
                Path(app_data) / "Opera Software" / "Opera Stable"
            )
        if browser:
            browsers = [browser]
        else:
            browsers = list(roots_by_browser)
        return [
            (name, root)
            for name in browsers
            for root in roots_by_browser.get(name, [])
            if root.exists()
        ]


def is_low_signal_url(url: str) -> bool:
    """True for mechanical navigation (auth/SSO redirects) that carries no user intent.

    Deliberately narrow so Ambient stays a substrate: search queries and content
    pages are kept and left for Hermes to judge.
    """
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if any(host == suffix or host.endswith("." + suffix) for suffix in _NOISE_HOST_SUFFIXES):
        return True
    segments = {seg for seg in parts.path.lower().split("/") if seg}
    if not segments & _NOISE_PATH_SEGMENTS:
        return False
    return any(keyword in host for keyword in _NOISE_HOST_KEYWORDS) or "login" in segments


def copy_sqlite_database(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{source}{suffix}")
        if sidecar.exists():
            shutil.copy2(sidecar, Path(f"{destination}{suffix}"))
    return destination


def sanitize_browser_url(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


class VideoCollector(Collector):
    source = "video"


_TITLE_NOISE = {"desktop", "nemo-desktop", "panel", "plank", "tint2"}

_KNOWN_APPS: dict[str, str] = {
    "mozilla firefox": "firefox",
    "firefox": "firefox",
    "google chrome": "chrome",
    "chromium": "chromium",
    "visual studio code": "vscode",
    "code - oss": "vscode",
    "sublime text": "sublime",
    "gnome terminal": "gnome-terminal",
    "konsole": "konsole",
    "alacritty": "alacritty",
    "kitty": "kitty",
    "wezterm": "wezterm",
    "nautilus": "nautilus",
    "nemo": "nemo",
    "thunar": "thunar",
    "discord": "discord",
    "slack": "slack",
    "obsidian": "obsidian",
    "pocket": "pocket",
}


def parse_window_title(raw: str) -> dict[str, str | None]:
    for sep in (" — ", " - ", " – "):
        if sep in raw:
            parts = raw.rsplit(sep, 1)
            content = parts[0].strip()
            suffix = parts[1].strip()
            app = _KNOWN_APPS.get(suffix.lower())
            if app:
                return {"title": content, "app": app, "raw": raw}
    return {"title": raw.strip(), "app": None, "raw": raw}


class AppWindowCollector(Collector):
    source = "app"

    def collect(self) -> list[AmbientEvent]:
        windows = self._list_windows()
        active_wid = self._active_window_id()
        now = datetime.now(timezone.utc).isoformat()
        events: list[AmbientEvent] = []
        for wid, raw_title in windows:
            if raw_title.lower() in _TITLE_NOISE or len(raw_title) < 3:
                continue
            parsed = parse_window_title(raw_title)
            meta: dict[str, object] = {}
            if parsed["app"]:
                meta["app"] = parsed["app"]
            if wid == active_wid:
                meta["active"] = True
            events.append(
                AmbientEvent(
                    source=self.source,
                    kind="window",
                    title=parsed["title"],
                    metadata=meta,
                    occurred_at=now,
                )
            )
        return events

    def _list_windows(self) -> list[tuple[str, str]]:
        if os.name == "nt":
            return _list_windows_win32()
        output = self._run_cmd(["wmctrl", "-l"])
        if output is not None:
            return _parse_wmctrl(output)
        title = self._xdotool(["getactivewindow", "getwindowname"])
        if title:
            wid = self._xdotool(["getactivewindow"]) or "0"
            return [(wid, title)]
        return []

    def _active_window_id(self) -> str | None:
        if os.name == "nt":
            return _active_window_id_win32()
        return self._xdotool(["getactivewindow"])

    def _xdotool(self, args: list[str]) -> str | None:
        return self._run_cmd(["xdotool", *args])

    def _run_cmd(self, args: list[str]) -> str | None:
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None


def _parse_wmctrl(output: str) -> list[tuple[str, str]]:
    windows: list[tuple[str, str]] = []
    for line in output.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        wid = parts[0]
        title = parts[3]
        windows.append((wid, title))
    return windows


def _active_window_id_win32() -> str | None:
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
    except AttributeError:
        return None
    return str(hwnd) if hwnd else None


def _list_windows_win32() -> list[tuple[str, str]]:
    try:
        user32 = ctypes.windll.user32
    except AttributeError:
        return []

    windows: list[tuple[str, str]] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if title:
            windows.append((str(hwnd), title))
        return True

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)(callback)
    user32.EnumWindows(enum_proc, 0)
    return windows


class RepoCollector(Collector):
    source = "repo"

    def __init__(self, repo_path: Path | None = None):
        self.repo_path = (repo_path or Path.cwd()).resolve()

    def collect(self) -> list[AmbientEvent]:
        root = self._git(["rev-parse", "--show-toplevel"])
        if root is None:
            return []

        repo_root = Path(root)
        branch = self._git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root) or "unknown"
        head = self._git(["rev-parse", "--short", "HEAD"], cwd=repo_root)
        status = self._git(["status", "--porcelain"], cwd=repo_root) or ""
        latest = self._git(["log", "-1", "--pretty=format:%h %s"], cwd=repo_root)
        changed_files = parse_status_files(status)
        status_digest = sha1(status.encode("utf-8")).hexdigest()[:12] if status else "clean"
        state = "dirty" if changed_files else "clean"
        now = datetime.now(timezone.utc).isoformat()
        repo_name = repo_root.name

        events = [
            AmbientEvent(
                source=self.source,
                kind="git_state",
                title=f"{repo_name} repo {state} on {branch} ({len(changed_files)} files, {status_digest})",
                metadata={
                    "repo": repo_name,
                    "branch": branch,
                    "head": head,
                    "dirty": bool(changed_files),
                    "status_digest": status_digest,
                    "changed_file_count": len(changed_files),
                    "changed_files": changed_files[:25],
                },
                occurred_at=now,
            )
        ]
        if latest:
            events.append(
                AmbientEvent(
                    source=self.source,
                    kind="git_commit",
                    title=f"{repo_name} latest commit {latest}",
                    metadata={"repo": repo_name, "branch": branch, "head": head},
                    occurred_at=now,
                )
            )
        return events

    def _git(self, args: list[str], cwd: Path | None = None) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=cwd or self.repo_path,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip()


class TerminalHistoryCollector(Collector):
    source = "terminal"

    def __init__(self, tail_lines: int = 25):
        self.tail_lines = tail_lines

    def collect(self) -> list[AmbientEvent]:
        history_path = self._find_history_file()
        if not history_path:
            return []
        lines = self._read_tail(history_path)
        if not lines:
            return []
        now = datetime.now(timezone.utc).isoformat()
        events: list[AmbientEvent] = []
        for cmd in lines:
            if not cmd or len(cmd) < 2:
                continue
            cmd = redact_command(cmd)
            events.append(
                AmbientEvent(
                    source=self.source,
                    kind="shell_command",
                    title=cmd,
                    metadata={"shell": history_path.name},
                    occurred_at=now,
                )
            )
        return events

    def _find_history_file(self) -> Path | None:
        home = Path.home()
        for name in (".zsh_history", ".bash_history"):
            path = home / name
            if path.exists() and path.stat().st_size > 0:
                return path
        return None

    def _read_tail(self, path: Path) -> list[str]:
        try:
            raw = path.read_bytes()
        except OSError:
            return []
        lines = raw.decode("utf-8", errors="replace").splitlines()
        recent = lines[-self.tail_lines:]
        cleaned: list[str] = []
        for line in recent:
            cmd = _clean_history_line(line)
            if cmd:
                cleaned.append(cmd)
        return cleaned


def _clean_history_line(line: str) -> str:
    line = line.strip()
    if not line or line.startswith("#"):
        return ""
    if line.startswith(": ") and ";" in line:
        line = line.split(";", 1)[1]
    return line.strip()


_KNOWN_PORTS: dict[int, str] = {
    5432: "postgres",
    3306: "mysql",
    6379: "redis",
    27017: "mongodb",
    8080: "http-alt",
    8081: "http-alt",
    3000: "dev-server",
    5000: "dev-server",
    5173: "vite",
    5174: "vite",
    4200: "angular",
    3001: "dev-server",
    8888: "jupyter",
    11434: "ollama",
    6463: "discord-rpc",
}


class SystemCollector(Collector):
    source = "system"

    def collect(self) -> list[AmbientEvent]:
        now = datetime.now(timezone.utc).isoformat()
        events: list[AmbientEvent] = []
        hw = self._hardware_profile()
        if hw:
            events.append(
                AmbientEvent(
                    source=self.source,
                    kind="hardware",
                    title=hw["summary"],
                    metadata=hw,
                    occurred_at=now,
                )
            )
        services = self._running_services()
        if services:
            names = [s["name"] for s in services]
            events.append(
                AmbientEvent(
                    source=self.source,
                    kind="services",
                    title=f"{len(services)} services: {', '.join(names)}",
                    metadata={"services": services},
                    occurred_at=now,
                )
            )
        return events

    def _hardware_profile(self) -> dict[str, object] | None:
        if os.name == "nt":
            return self._hardware_profile_windows()
        cpu = self._read_cpu()
        mem = self._read_mem()
        gpu = self._read_gpu()
        disk = self._read_disk()
        if not cpu and not mem:
            return None
        parts = []
        if cpu:
            parts.append(cpu)
        if mem:
            parts.append(mem)
        if gpu:
            parts.append(gpu)
        if disk:
            parts.append(disk)
        profile: dict[str, object] = {"summary": " | ".join(parts)}
        if cpu:
            profile["cpu"] = cpu
        if mem:
            profile["mem"] = mem
        if gpu:
            profile["gpu"] = gpu
        if disk:
            profile["disk"] = disk
        return profile

    def _hardware_profile_windows(self) -> dict[str, object] | None:
        cpu = platform.processor() or platform.machine()
        cores = os.cpu_count() or 0
        mem = _windows_total_memory()
        disk = _disk_summary()
        parts = []
        if cpu:
            parts.append(f"{cpu} ({cores} cores)")
        if mem:
            parts.append(mem)
        if disk:
            parts.append(disk)
        if not parts:
            return None
        profile: dict[str, object] = {"summary": " | ".join(parts)}
        if cpu:
            profile["cpu"] = f"{cpu} ({cores} cores)"
        if mem:
            profile["mem"] = mem
        if disk:
            profile["disk"] = disk
        return profile

    def _read_cpu(self) -> str:
        try:
            lines = Path("/proc/cpuinfo").read_text().splitlines()
        except OSError:
            return ""
        model = ""
        cores = 0
        for line in lines:
            if line.startswith("model name") and not model:
                model = line.split(":", 1)[1].strip()
            if line.startswith("processor"):
                cores += 1
        if not model:
            return ""
        return f"{model} ({cores} cores)"

    def _read_mem(self) -> str:
        try:
            lines = Path("/proc/meminfo").read_text().splitlines()
        except OSError:
            return ""
        for line in lines:
            if line.startswith("MemTotal:"):
                kb = int(line.split()[1])
                gb = round(kb / 1024 / 1024, 1)
                return f"{gb}GB RAM"
        return ""

    def _read_gpu(self) -> str:
        try:
            result = subprocess.run(
                ["lspci"], capture_output=True, text=True, check=False, timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if result.returncode != 0:
            return ""
        for line in result.stdout.splitlines():
            low = line.lower()
            if "vga" in low or "3d" in low or "display" in low:
                return line.split(":", 2)[-1].strip() if ":" in line else line.strip()
        return ""

    def _read_disk(self) -> str:
        try:
            result = subprocess.run(
                ["df", "-h", "/"], capture_output=True, text=True, check=False, timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if result.returncode != 0:
            return ""
        lines = result.stdout.strip().splitlines()
        if len(lines) < 2:
            return ""
        parts = lines[1].split()
        if len(parts) >= 4:
            return f"{parts[3]} free / {parts[1]} disk"
        return ""

    def _running_services(self) -> list[dict[str, object]]:
        services: list[dict[str, object]] = []
        services.extend(self._docker_containers())
        if os.name == "nt":
            services.extend(self._listening_ports_windows())
        else:
            services.extend(self._listening_ports())
        return services

    def _docker_containers(self) -> list[dict[str, object]]:
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}"],
                capture_output=True, text=True, check=False, timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            return []
        containers: list[dict[str, object]] = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                containers.append({
                    "name": parts[0],
                    "type": "docker",
                    "image": parts[1],
                    "status": parts[2] if len(parts) >= 3 else "",
                })
        return containers

    def _listening_ports_windows(self) -> list[dict[str, object]]:
        try:
            result = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            return []
        services: list[dict[str, object]] = []
        seen_ports: set[int] = set()
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[0].lower() != "tcp" or parts[3].upper() != "LISTENING":
                continue
            port = _parse_endpoint_port(parts[1])
            if port is None or port in seen_ports:
                continue
            seen_ports.add(port)
            services.append({
                "name": _KNOWN_PORTS.get(port, f"port-{port}"),
                "type": "listener",
                "port": port,
                "pid": parts[4],
            })
        return services

    def _listening_ports(self) -> list[dict[str, object]]:
        output = self._run_ss()
        if not output:
            return []
        services: list[dict[str, object]] = []
        seen_ports: set[int] = set()
        for line in output.splitlines():
            if "LISTEN" not in line:
                continue
            port = _parse_ss_port(line)
            if port is None or port in seen_ports:
                continue
            name = _KNOWN_PORTS.get(port)
            if not name:
                name = _parse_ss_process(line) or f"port-{port}"
            seen_ports.add(port)
            services.append({"name": name, "type": "listener", "port": port})
        return services

    def _run_ss(self) -> str:
        try:
            result = subprocess.run(
                ["ss", "-tlnp"],
                capture_output=True, text=True, check=False, timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if result.returncode != 0:
            return ""
        return result.stdout


def _parse_ss_port(line: str) -> int | None:
    parts = line.split()
    for part in parts:
        if ":" in part:
            port_str = part.rsplit(":", 1)[-1]
            if port_str.isdigit():
                port = int(port_str)
                if port > 0:
                    return port
    return None


def _parse_endpoint_port(endpoint: str) -> int | None:
    port_str = endpoint.rsplit(":", 1)[-1].strip("[]")
    if port_str.isdigit():
        port = int(port_str)
        if port > 0:
            return port
    return None


def _parse_ss_process(line: str) -> str:
    if 'users:(("' in line:
        start = line.index('users:(("') + 9
        end = line.index('"', start)
        return line[start:end]
    return ""


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _windows_total_memory() -> str:
    try:
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return ""
    except AttributeError:
        return ""
    gb = round(status.ullTotalPhys / 1024 / 1024 / 1024, 1)
    return f"{gb}GB RAM"


def _disk_summary() -> str:
    try:
        usage = shutil.disk_usage(Path.cwd().anchor or Path.cwd())
    except OSError:
        return ""
    free = round(usage.free / 1024 / 1024 / 1024, 1)
    total = round(usage.total / 1024 / 1024 / 1024, 1)
    return f"{free}GB free / {total}GB disk"


class VoiceCollector(Collector):
    source = "voice"


class AthenaCollector(Collector):
    source = "athena"


def sample_events() -> list[AmbientEvent]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        AmbientEvent(
            source="video",
            kind="youtube_watch",
            title="Open model X: local inference and hardware requirements",
            url="https://www.youtube.com/watch?v=example-model-x",
            artifact_ref="artifacts/transcripts/example-model-x.txt",
            metadata={"channel": "Local AI Lab", "duration_seconds": 1210},
            occurred_at=now,
        ),
        AmbientEvent(
            source="browser",
            kind="tab",
            title="Model X GitHub repository",
            url="https://github.com/example/model-x",
            metadata={"window_title": "Model X - GitHub"},
            occurred_at=now,
        ),
        AmbientEvent(
            source="repo",
            kind="git_activity",
            title="ambient-ai scaffold created",
            metadata={"branch": "main", "dirty": True},
            occurred_at=now,
        ),
        AmbientEvent(
            source="athena",
            kind="session",
            title="Ambient AI project bootstrap",
            artifact_ref=".context-workspace/hermes/session-recall.md",
            metadata={"agent": "Codex"},
            occurred_at=now,
        ),
    ]


def parse_status_files(status: str) -> list[str]:
    files: list[str] = []
    for line in status.splitlines():
        if not line:
            continue
        path = line[3:] if len(line) > 3 else line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path)
    return files
