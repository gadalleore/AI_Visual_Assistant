#!/usr/bin/env python3
r"""
AI Visual Assistant - Screen Watcher

High-frequency screen capture tool so an AI (Grok, Claude, Cursor, etc.) can
"see" your desktop in near real time via local PNG files.

=== FOLLOW MODE ===
Magic phrases (say to your AI):
  "Follow Mode On"   → persistent flag + high-speed capture
  "Follow Mode Off"  → stop

While on, the AI can watch mouse gestures, UI state, errors, etc.

**Real-time note-based interaction rules (important):**
- Give instructions in **only 2 to 3 sentences at a time**.
- If the user has not written a new question on the screen note, simply repeat your previous 2-3 sentences.
- Always use `follow grab` (or `--json`) before responding to read the latest on-screen note.
- This keeps the interaction paced in real time with the user's typing.

Primary recommended flow for any AI:
  1. py screen_watcher.py follow on
  2. py screen_watcher.py --fast          (or --realtime)
  3. (later, when you want the AI to look)  py screen_watcher.py follow grab
  4. AI reads the printed stable paths with its vision tool (current.png + recent frames)

Safety: Follow mode **automatically turns itself off after 60 minutes** of continuous use.
You can always turn it back on.

Reliability: Capture is resilient (safe monitor selection + mss→PIL fallback at runtime).
The watcher recovers from transient capture failures instead of dying. Automatic bounded
garbage collection (including for stable grab/ snapshots) prevents folders from growing
unbounded even under heavy one-shot or AI-driven usage.

Fast presets:
    py screen_watcher.py --fast
    py screen_watcher.py --realtime

Key follow subcommands (designed for both humans and AI agents):
    follow on / off / status
    follow grab          # BEST for AIs — creates stable non-rotating files in screenshots/grab/
    follow stream        # quick list (use grab for reliability)
    follow live / observe
    follow status --json
    follow grab --json
    follow instructions

See: py screen_watcher.py follow instructions   (or read FOLLOW_MODE_INSTRUCTIONS.txt)

=== Why "grab" exists ===
The rotating recent/ ring buffer is great for low disk use, but frames can disappear
between an AI listing paths and actually reading the images.
`follow grab` copies the current state into a stable `grab/` directory (the background
watcher does not clean it). Grab is self-managing: it automatically prunes old artifacts
on each new grab so the folder stays bounded even with heavy use.

Privacy: Only use when comfortable. Everything is local and short-lived by default.
"""

from __future__ import annotations

__version__ = "0.2.0"

import argparse
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import ImageGrab

# Optional faster backend for high-frequency follow mode (mouse circling etc.)
try:
    import mss
    import mss.tools
    _HAS_MSS = True
except Exception:
    _HAS_MSS = False

# Where we store screenshots (user home, not in the project)
BASE_DIR = Path.home() / ".ai-visual-assistant"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
LATEST_TXT = BASE_DIR / "latest_screenshot.txt"
CURRENT_PNG = SCREENSHOTS_DIR / "current.png"
LAST_CONTEXT_FILE = BASE_DIR / "last_session_context.txt"

# Follow mode state (so the controlling AI can persistently know if "Follow Mode On" was requested)
FOLLOW_MODE_FILE = BASE_DIR / "follow_mode.txt"
FOLLOW_STARTED_FILE = BASE_DIR / "follow_mode_started.txt"  # ISO timestamp when "on" was set
FOLLOW_TASK_FILE = BASE_DIR / "follow_task_id.txt"   # written by the AI harness when it launches via background tool
RECENT_DIR = SCREENSHOTS_DIR / "recent"
RECENT_BUFFER_SIZE = 60   # ~35-60s of recent history at 0.6-1s interval. Much more reliable for AI "following" sequences.

# Stable grab location for AIs (Grok, Claude, Cursor, etc.) to safely read without race with rotation
GRAB_DIR = SCREENSHOTS_DIR / "grab"
GRAB_RECENT_DIR = GRAB_DIR / "recent"

FOLLOW_TIMEOUT_SECONDS = 3600  # 1 hour hard safety limit. Auto-disables if left on too long.


def ensure_dirs() -> None:
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    RECENT_DIR.mkdir(parents=True, exist_ok=True)


def set_follow_mode(enabled: bool) -> None:
    """Persistently record whether Follow Mode is on.
    Also records the start timestamp so we can enforce the 1-hour safety auto-off.
    """
    ensure_dirs()
    FOLLOW_MODE_FILE.write_text("on" if enabled else "off", encoding="utf-8")
    if enabled:
        FOLLOW_STARTED_FILE.write_text(datetime.now().isoformat(), encoding="utf-8")
    else:
        FOLLOW_STARTED_FILE.unlink(missing_ok=True)


def is_follow_mode() -> bool:
    """Check the persisted follow mode flag. Used by me and by the watcher."""
    try:
        return FOLLOW_MODE_FILE.read_text(encoding="utf-8").strip().lower() == "on"
    except Exception:
        return False


def get_follow_task_id() -> str | None:
    try:
        tid = FOLLOW_TASK_FILE.read_text(encoding="utf-8").strip()
        return tid or None
    except Exception:
        return None


def set_follow_task_id(task_id: str | None) -> None:
    ensure_dirs()
    if task_id:
        FOLLOW_TASK_FILE.write_text(str(task_id), encoding="utf-8")
    else:
        FOLLOW_TASK_FILE.unlink(missing_ok=True)


def get_follow_started() -> datetime | None:
    """Return when Follow Mode was turned on (for timeout and status)."""
    try:
        if FOLLOW_STARTED_FILE.exists():
            ts = FOLLOW_STARTED_FILE.read_text(encoding="utf-8").strip()
            return datetime.fromisoformat(ts)
    except Exception:
        pass
    return None


def follow_duration_seconds() -> float:
    started = get_follow_started()
    if started:
        return (datetime.now() - started).total_seconds()
    return 0.0


def enforce_follow_timeout() -> bool:
    """If Follow Mode has been on longer than FOLLOW_TIMEOUT_SECONDS, auto-disable it.
    Returns True if it was just turned off by the timeout.
    """
    if not is_follow_mode():
        return False
    started = get_follow_started()
    if started:
        elapsed = (datetime.now() - started).total_seconds()
        if elapsed > FOLLOW_TIMEOUT_SECONDS:
            set_follow_mode(False)
            print(f"[SAFETY] Follow Mode was on for {elapsed/60:.1f} minutes (>1 hour) — automatically disabled.")
            print("You (or the AI) can turn it back on with 'follow on' if you really need to continue.")
            return True
    return False


def capture_screenshot() -> Path:
    """Capture the screen (prefers fast mss backend when available). Returns path to the new timestamped file.

    Resilient: safe monitor selection, runtime fallback from mss to PIL.ImageGrab,
    and best-effort but warned update of current.png. A single transient failure
    should not kill a running watcher.
    """
    ensure_dirs()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"screen_{timestamp}.png"
    filepath = SCREENSHOTS_DIR / filename

    last_err: Exception | None = None
    captured = False

    # Prefer mss (fast path) but be defensive at runtime even if the import succeeded.
    if _HAS_MSS:
        try:
            with mss.MSS() as sct:
                mons = sct.monitors
                # Safe selection: monitors[0] is the virtual "all monitors" desktop.
                # monitors[1] is usually the primary. Fall back gracefully.
                mon = mons[1] if len(mons) > 1 else mons[0]
                sct_img = sct.grab(mon)
                mss.tools.to_png(sct_img.rgb, sct_img.size, output=str(filepath))
            captured = True
        except Exception as e:
            last_err = e
            # Fall through to PIL fallback

    if not captured:
        try:
            im = ImageGrab.grab()
            im.save(filepath, "PNG")
            captured = True
        except Exception as e:
            last_err = e

    if not captured or not filepath.exists():
        # Surface a clear error so callers (grab, live, watcher) can decide what to do.
        raise RuntimeError(f"Screen capture failed (tried mss + PIL): {last_err}") from last_err

    # Reliably update the "current.png" live view from the file we just successfully wrote.
    # Previously this was completely silent on failure, which could make follow grab
    # and other commands appear to stop producing usable screenshots.
    try:
        shutil.copy2(filepath, CURRENT_PNG)
    except Exception as e:
        print(f"[WARN] Captured fresh screenshot to {filepath}")
        print(f"       but failed to update {CURRENT_PNG}: {e}")
        print("       The timestamped file is still valid — you can use it directly.")

    try:
        LATEST_TXT.write_text(str(filepath), encoding="utf-8")
    except Exception:
        pass

    # Opportunistic garbage collection for the main screenshots directory.
    # This ensures that *one-shot* usage (--once, follow grab, follow live, bare "live", etc.)
    # also participates in cleanup. Without a long-running watcher the previous logic
    # could let screen_*.png pile up indefinitely.
    #
    # We use deliberately generous limits here (hours + hundreds of files). The running
    # watcher will apply its own tighter --max-age/--max-keep policy on its next tick.
    # Wrapped so a cleanup hiccup can never affect the just-taken screenshot.
    try:
        cleanup_old(max_age_seconds=4 * 3600, max_files=300)  # 4 hours or 300 files, very permissive
    except Exception:
        pass

    return filepath


def cleanup_old(max_age_seconds: int = 300, max_files: int = 5) -> int:
    """Delete old timestamped screenshots. Returns number of files deleted."""
    ensure_dirs()
    if not SCREENSHOTS_DIR.exists():
        return 0

    now = time.time()
    candidates = sorted(
        SCREENSHOTS_DIR.glob("screen_*.png"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    deleted = 0
    kept = 0
    for p in candidates:
        try:
            age = now - p.stat().st_mtime
            if age > max_age_seconds or kept >= max_files:
                p.unlink(missing_ok=True)
                deleted += 1
            else:
                kept += 1
        except Exception:
            # Never let cleanup crash the watcher
            pass

    # If we deleted everything recent, also remove the "current.png" convenience file
    if kept == 0:
        try:
            CURRENT_PNG.unlink(missing_ok=True)
        except Exception:
            pass

    return deleted


def get_latest_path() -> Path | None:
    if LATEST_TXT.exists():
        p = Path(LATEST_TXT.read_text(encoding="utf-8").strip())
        if p.exists():
            return p
    # Fallback: most recent file on disk
    files = sorted(SCREENSHOTS_DIR.glob("screen_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def save_recent_frame(source: Path, buffer_size: int = RECENT_BUFFER_SIZE) -> Path | None:
    """Copy the latest capture into a small rotating 'recent/' ring buffer.
    This lets the AI read the last several frames in parallel to understand motion
    like you circling something with the mouse.
    """
    ensure_dirs()
    if not source.exists():
        return None

    ts = datetime.now().strftime("%H%M%S%f")[:-3]
    dest = RECENT_DIR / f"frame_{ts}.png"
    try:
        shutil.copy2(source, dest)
    except Exception:
        return None

    # Trim to keep only the most recent N frames (by mtime)
    try:
        frames = sorted(RECENT_DIR.glob("frame_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in frames[buffer_size:]:
            old.unlink(missing_ok=True)
    except Exception:
        pass

    return dest


def get_recent_frame_paths(limit: int = 6) -> list[Path]:
    """Return the most recent frame paths (newest first) from the ring buffer.
    For AI agents (Grok, Claude, Cursor, etc.) to read several frames in parallel for motion/context.
    """
    ensure_dirs()
    frames = sorted(RECENT_DIR.glob("frame_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return frames[:limit]


def grab_stable_snapshot(num_recent: int = 20, fresh_capture: bool = True) -> list[Path]:
    """Create a *stable*, non-rotating snapshot of the current screen state into
    screenshots/grab/ (and grab/recent/).

    This is the **recommended command for any AI agent** (Grok, Claude, Cursor, Aider, etc.)
    to reliably collect visuals. The watcher loop does not touch grab/ (by design),
    but grab/ is self-managing: after each new grab we automatically prune old
    artifacts in grab/recent/ and very old files so the directory cannot grow
    to infinity even if "follow grab" is called hundreds of times.

    - fresh_capture=True (default) ensures the very latest frame is included.
    - Copies current.png + up to num_recent recent frames.
    - The just-created snapshot is always preserved; only older historical grab files are reaped.

    Returns the list of stable absolute paths (read these with your vision tool).
    """
    ensure_dirs()
    GRAB_DIR.mkdir(parents=True, exist_ok=True)
    GRAB_RECENT_DIR.mkdir(parents=True, exist_ok=True)

    grabbed: list[Path] = []

    if fresh_capture:
        capture_screenshot()
        # Always seed the recent ring on an explicit fresh capture (grab/live).
        # This makes "follow grab" useful for motion context even if no background
        # --fast watcher is currently running and follow_mode flag is off.
        save_recent_frame(CURRENT_PNG)

    # Stable current view
    if CURRENT_PNG.exists():
        dst = GRAB_DIR / "current.png"
        try:
            shutil.copy2(CURRENT_PNG, dst)
            grabbed.append(dst)
        except Exception:
            pass

    # Copy generous recent history into stable location
    recent = get_recent_frame_paths(num_recent)
    for src in recent:
        if src.exists():
            dst = GRAB_RECENT_DIR / src.name
            try:
                shutil.copy2(src, dst)
                grabbed.append(dst)
            except Exception:
                pass

    # Self-prune the grab area so it doesn't grow without bound across many
    # "follow grab" invocations (the main source of "folder balloons to infinity").
    # We keep a comfortable amount of history for the just-created stable snapshot
    # while discarding older grab artifacts.
    try:
        cleaned = cleanup_grab(max_recent=150, max_age_seconds=172800)  # ~2 days, 150 recent frames
        if cleaned > 0:
            # Quietly note it only in non-AI-facing paths; grab output stays clean.
            pass
    except Exception:
        pass

    return grabbed


def cleanup_recent(max_files: int = 0) -> int:
    """Aggressive trim of the recent buffer (used in follow mode)."""
    deleted = 0
    try:
        frames = sorted(RECENT_DIR.glob("frame_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        if max_files > 0:
            for old in frames[max_files:]:
                old.unlink(missing_ok=True)
                deleted += 1
        else:
            # delete all
            for f in frames:
                f.unlink(missing_ok=True)
                deleted += 1
    except Exception:
        pass
    return deleted


def cleanup_grab(max_recent: int = 150, max_age_seconds: int = 172800) -> int:
    """Bounded cleanup of the stable grab/ area.

    The grab/ directory is intentionally not rotated by the normal watcher
    (so the AI has stable files to read). However, repeated "follow grab"
    calls (common when an AI is actively observing) can cause grab/recent/
    to accumulate old frames forever because we copy by basename.

    This function is called automatically after each grab_stable_snapshot
    to keep the stable area from ballooning, while still preserving the
    just-created snapshot and a generous amount of recent history for it.

    Also prunes very old files from the grab root (except the current one).
    """
    deleted = 0
    try:
        GRAB_DIR.mkdir(parents=True, exist_ok=True)
        GRAB_RECENT_DIR.mkdir(parents=True, exist_ok=True)

        now = time.time()

        # 1. Trim grab/recent/ to a bounded number of the newest frames.
        if GRAB_RECENT_DIR.exists():
            gframes = sorted(
                GRAB_RECENT_DIR.glob("frame_*.png"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old in gframes[max_recent:]:
                try:
                    old.unlink(missing_ok=True)
                    deleted += 1
                except Exception:
                    pass

        # 2. Remove very old individual files inside grab/ (but keep the latest current.png).
        #    This catches historical grab/current.png copies if someone renamed or extra files.
        current_grab = GRAB_DIR / "current.png"
        for f in GRAB_DIR.glob("*.png"):
            if f == current_grab:
                continue
            try:
                if now - f.stat().st_mtime > max_age_seconds:
                    f.unlink(missing_ok=True)
                    deleted += 1
            except Exception:
                pass

        # 3. Also trim anything left in grab/recent/ that is extremely old.
        if GRAB_RECENT_DIR.exists():
            for f in GRAB_RECENT_DIR.glob("frame_*.png"):
                try:
                    if now - f.stat().st_mtime > max_age_seconds:
                        f.unlink(missing_ok=True)
                        deleted += 1
                except Exception:
                    pass

    except Exception:
        # Never let grab cleanup break the grab operation or the caller.
        pass

    return deleted


def watch_loop(interval: float, max_age: int, max_keep: int, follow: bool = False, recent_buffer: int = 0) -> None:
    ensure_dirs()
    follow_active = follow or is_follow_mode()

    # 1-hour safety timeout check at startup
    if follow_active:
        enforce_follow_timeout()
        follow_active = is_follow_mode()  # may have been turned off by the check

    print("AI Visual Assistant - Screen Watcher")
    print(f"  Screenshots folder : {SCREENSHOTS_DIR}")
    print(f"  Capture interval   : {interval}s")
    print(f"  Auto-delete after  : {max_age}s or when >{max_keep} files")
    if follow_active:
        buf = recent_buffer or RECENT_BUFFER_SIZE
        print(f"  FOLLOW MODE        : ON (recent buffer ~{buf} frames for motion/context)")
        print("                       current.png + recent/frame_*.png  (use 'follow grab' for stable AI reads)")
    print()
    print("Watcher is now ACTIVE.")
    if follow_active:
        print("FOLLOW STREAM READY. The AI can watch what you are doing in near real time.")
        print("Preferred for agents: tell the AI to run 'py screen_watcher.py follow grab' then read those paths.")
    else:
        print("I will take a screenshot every interval and print the path.")
    print()
    print("To have the AI see your screen right now:")
    print("  - Latest live view: " + str(CURRENT_PNG))
    if follow_active:
        print("  - Best for reliable observation:  py screen_watcher.py follow grab")
        print("    (creates stable files in screenshots/grab/ that won't rotate away)")
    print()
    print("Stop watching with Ctrl+C")
    print("-" * 60)

    effective_interval = interval
    buf_size = recent_buffer or (RECENT_BUFFER_SIZE if follow_active else 0)

    try:
        while True:
            try:
                path = capture_screenshot()
            except Exception as e:
                # Do not let one bad capture (transient display glitch, driver hiccup, etc.)
                # kill the entire watcher session. Log and keep going.
                print(f"[WARN] Screenshot capture failed: {e}")
                print("       Will retry on the next interval.")
                print("       (If this persists, check display settings, drivers, or try without mss.)")
                time.sleep(effective_interval)
                continue

            if buf_size > 0:
                save_recent_frame(CURRENT_PNG, buffer_size=buf_size)

            if follow_active:
                print(f"Follow capture: current.png updated")
            else:
                print(f"Captured: {path}")
                print(f"          current.png (always the latest) also updated")

            # In follow mode: keep a generous recent buffer, longer history, less aggressive cleanup.
            if follow_active:
                deleted_hist = cleanup_old(max_age, max_keep)
                # Keep most of the configured buffer (much less aggressive than before)
                keep_recent = max(8, buf_size - 4)
                deleted_recent = cleanup_recent(keep_recent)
                if deleted_hist or deleted_recent:
                    print(f"          (cleaned history/recent)")
            else:
                deleted = cleanup_old(max_age, max_keep)
                if deleted:
                    print(f"          (cleaned {deleted} old screenshot(s))")

            # Periodic safety timeout check (every capture in follow mode is fine)
            if follow_active:
                if enforce_follow_timeout():
                    follow_active = False
                    print("Follow mode auto-disabled due to 1-hour limit.")
                    break
                if not is_follow_mode():
                    print("\nFollow mode has been turned off. Shutting down the observation stream...")
                    break

            if not follow and is_follow_mode() != follow_active:
                follow_active = is_follow_mode()
                print("          [follow mode flag changed while running]")

            time.sleep(effective_interval)
    except KeyboardInterrupt:
        print("\n\nScreen watcher stopped by user.")
        print("Any remaining recent screenshots are still in:")
        print(f"  {SCREENSHOTS_DIR}")
        if follow_active:
            print(f"  Recent frames (for motion): {RECENT_DIR}")
        print("Run with --cleanup or 'py screen_watcher.py follow off' later if you want to remove them now.")


def open_screenshots_dir() -> None:
    ensure_dirs()
    try:
        # Windows Explorer
        subprocess.Popen(["explorer", str(SCREENSHOTS_DIR)])
        print(f"Opened: {SCREENSHOTS_DIR}")
    except Exception as e:
        print(f"Could not open folder automatically: {e}")
        print(f"Please open manually: {SCREENSHOTS_DIR}")


def print_follow_instructions() -> None:
    """Print concise instructions focused on Follow Mode + the magic phrases.
    Prefers the external FOLLOW_MODE_INSTRUCTIONS.txt (the source of truth) when present.
    """
    ensure_dirs()
    # Look for the nice text file next to the .py or in common locations
    candidates = [
        Path(__file__).with_name("FOLLOW_MODE_INSTRUCTIONS.txt"),
        BASE_DIR / "FOLLOW_MODE_INSTRUCTIONS.txt",
        (BASE_DIR.parent / "AI Visual Assistant" / "FOLLOW_MODE_INSTRUCTIONS.txt"),
    ]
    for cand in candidates:
        if cand and cand.exists():
            print(cand.read_text(encoding="utf-8"))
            return

    # Fallback (should rarely happen)
    print("See FOLLOW_MODE_INSTRUCTIONS.txt next to screen_watcher.py, or run the file directly.")
    print("Magic phrases: \"Follow Mode On\" and \"Follow Mode Off\" in this chat.")


def do_follow_command(args_list: list[str]) -> None:
    """Lightweight subcommand handler for 'py screen_watcher.py follow ...'.

    Designed to be easy for any AI agent (Grok, Claude, Cursor, etc.) to drive via terminal.
    Preferred reliable collection command for agents: `follow grab` (creates stable files).
    """
    if not args_list:
        print("follow subcommands: on, off, status, latest, stream, grab, live, cleanup, instructions, save-context")
        print("  Add --json to stream/status/grab for machine-readable output (great for agents).")
        return

    # Support --json for agent consumption (Claude/Grok/etc.)
    lower_args = [a.lower() for a in args_list]
    as_json = "--json" in lower_args
    # Filter out the flag so the rest of the parser stays simple
    clean_args = [a for a in args_list if a.lower() != "--json"]

    if not clean_args:
        print("follow subcommands: on, off, status, latest, stream, grab, live, cleanup, instructions")
        return

    cmd = clean_args[0].lower()

    # Always check timeout on mutating or observation commands
    if cmd in ("on", "status", "stream", "grab", "snapshot", "collect", "live", "observe"):
        enforce_follow_timeout()

    if cmd in ("on", "enable"):
        set_follow_mode(True)
        print("Follow Mode is now ON (persistent flag set).")
        print("Start a fast watcher:  py screen_watcher.py --fast   (or --realtime)")
        print(f"Live view: {CURRENT_PNG}")
        print(f"Recent frames (ring): {RECENT_DIR}")
        print("For reliable AI collection use:  py screen_watcher.py follow grab   (then read the printed paths)")
        print("Safety: will auto-disable after 60 minutes of continuous use.")
        if LAST_CONTEXT_FILE.exists():
            ctx = LAST_CONTEXT_FILE.read_text(encoding="utf-8").strip()
            if ctx:
                print("\n--- Last saved session context ---")
                print(ctx)
                print("----------------------------------")

    elif cmd in ("off", "disable", "stop"):
        set_follow_mode(False)
        tid = get_follow_task_id()
        if tid:
            print(f"Follow mode flag cleared. (Background task id was {tid})")
            set_follow_task_id(None)
        else:
            print("Follow mode flag cleared.")
        print("If a watcher is running in a terminal, press Ctrl+C there.")
        print("The watcher will detect the flag and shut down on its next cycle.")
        # Optional: also clear any grab? We leave grab/ alone so the last observation remains readable.

    elif cmd in ("save-context", "context", "note", "save-note"):
        if len(clean_args) > 1:
            context = ' '.join(clean_args[1:])
            LAST_CONTEXT_FILE.write_text(context, encoding="utf-8")
            print("Session context saved. It will be shown the next time Follow Mode is turned on.")
        else:
            if LAST_CONTEXT_FILE.exists():
                print("Current saved session context:")
                print(LAST_CONTEXT_FILE.read_text(encoding="utf-8"))
            else:
                print("No context saved yet.")
                print("Usage: py screen_watcher.py follow save-context We were debugging the login flow...")

    elif cmd == "status":
        on = is_follow_mode()
        dur = follow_duration_seconds()
        print(f"Follow Mode: {'ON' if on else 'OFF'}")
        if on and dur > 0:
            mins = dur / 60
            remaining = max(0, (FOLLOW_TIMEOUT_SECONDS - dur) / 60)
            print(f"  on for: {mins:.1f} min  (auto-off in ~{remaining:.0f} min)")
        print(f"  current.png   : {CURRENT_PNG}  (exists: {CURRENT_PNG.exists()})")
        recent_count = len(list(RECENT_DIR.glob("frame_*.png")))
        print(f"  recent frames : {recent_count} in {RECENT_DIR}  (ring buffer)")
        recent = get_recent_frame_paths(5)
        if recent:
            print("  newest recent :")
            for p in recent:
                print(f"    {p}")
        grab_current = GRAB_DIR / "current.png"
        if grab_current.exists():
            print(f"  last grab     : {GRAB_DIR}  (stable — safe for AI to read)")
        tid = get_follow_task_id()
        if tid:
            print(f"  AI task id    : {tid}")
        if LAST_CONTEXT_FILE.exists():
            ctx = LAST_CONTEXT_FILE.read_text(encoding="utf-8").strip()
            if ctx:
                short = ctx if len(ctx) <= 80 else ctx[:77] + "..."
                print(f"  last context  : {short}")
        print(f"  follow flag file: {FOLLOW_MODE_FILE}")

    elif cmd == "latest":
        p = CURRENT_PNG if CURRENT_PNG.exists() else get_latest_path()
        if p:
            print(p)
        else:
            print("No current screenshot yet.")

    elif cmd == "stream":
        # Legacy / quick list. For confident AI use, prefer "grab" (stable files that won't vanish).
        paths = [CURRENT_PNG] + get_recent_frame_paths(12)
        seen = set()
        out_paths = []
        for p in paths:
            if p.exists() and str(p) not in seen:
                out_paths.append(p)
                seen.add(str(p))
        if as_json:
            import json
            print(json.dumps({
                "mode": "stream",
                "note": "These paths may rotate soon. Prefer 'follow grab' for stable collection.",
                "paths": [str(p) for p in out_paths]
            }, indent=2))
        else:
            for p in out_paths:
                print(p)
            if not out_paths:
                print("No frames yet. Start a watcher in follow/fast mode first.")
            else:
                print("(Note: these are live ring-buffer paths. For reliable AI reading use `follow grab` instead.)")

    elif cmd in ("grab", "snapshot", "collect", "pin", "freeze", "view"):
        # THE recommended command for any AI agent.
        # Creates stable copies in screenshots/grab/ that will not be deleted while the AI reads them.
        paths = grab_stable_snapshot(num_recent=25, fresh_capture=True)
        if as_json:
            import json
            print(json.dumps({
                "mode": "grab",
                "grab_dir": str(GRAB_DIR),
                "stable_paths": [str(p) for p in paths],
                "instructions": "Read these paths with your vision/file tool. They are safe from rotation."
            }, indent=2))
        else:
            if paths:
                print("=== STABLE GRAB (safe for AI vision) ===")
                for p in paths:
                    print(p)
                print(f"\nGrab location (stable): {GRAB_DIR}")
                print("The AI should now read the paths above (especially grab/current.png + grab/recent/*).")
                print("Old grab artifacts are automatically pruned over time to prevent unbounded growth.")
                print("Use 'follow cleanup' for a full manual wipe.")
            else:
                print("Nothing to grab yet. Make sure a watcher is running (py screen_watcher.py --fast).")

    elif cmd in ("live", "observe", "now", "current"):
        # Fresh capture + print live paths (current first). Good for "what am I doing right now?"
        p = capture_screenshot()
        # Always seed recent ring for explicit live observation commands.
        save_recent_frame(CURRENT_PNG)
        print(CURRENT_PNG)
        for r in get_recent_frame_paths(5):
            if r.exists():
                print(r)
        print("(Primary live view is the first path — read it with your vision tool.)")

    elif cmd in ("cleanup", "clean"):
        d1 = cleanup_old(0, 0)
        d2 = cleanup_recent(0)
        # Use the same bounded grab cleaner that runs automatically after grabs.
        # The manual full-nuke behavior is still achieved because we also aggressively
        # delete everything left (for users who really want a total wipe).
        grab_cleaned = cleanup_grab(max_recent=0, max_age_seconds=0)
        # Extra pass: ensure truly everything in grab/ is gone for the "clean" command
        # (the max_recent=0 / age=0 above will have trimmed aggressively).
        try:
            for f in list(GRAB_DIR.glob("**/*")):
                if f.is_file():
                    f.unlink(missing_ok=True)
                    grab_cleaned += 1
        except Exception:
            pass
        print(f"Cleaned {d1 + d2} main files + {grab_cleaned} grab files.")

    elif cmd in ("instructions", "help", "usage"):
        print_follow_instructions()

    else:
        print(f"Unknown follow subcommand: {cmd}")
        print("Try: on, off, status, latest, stream, grab, live, cleanup, instructions")
        print("Best for AIs:  follow grab   (then read the printed stable paths)")


def main() -> None:
    # Support the 'follow' subcommand early (before normal argparse) for nice UX:
    #   py screen_watcher.py follow on
    #   py screen_watcher.py follow stream
    # Also support bare "live" / "observe" for the fastest real-time path.
    if len(sys.argv) > 1:
        first = sys.argv[1].lower()
        if first == "follow":
            do_follow_command(sys.argv[2:])
            return
        if first in ("live", "observe"):
            # Quick real-time observation entry point
            p = capture_screenshot()
            # Always seed recent ring for explicit live observation.
            save_recent_frame(CURRENT_PNG)
            print(CURRENT_PNG)  # Primary path for me to read right now
            for r in get_recent_frame_paths(2):
                if r.exists():
                    print(r)
            return

    parser = argparse.ArgumentParser(
        description="Screen watcher for AI Visual Assistant. Lets AI assistants (Grok, Claude, etc.) see your desktop via temporary local screenshots.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=10.0,
        help="Seconds between automatic screenshots (default: 10). Use 0.6-1.0 for following mouse/actions.",
    )
    parser.add_argument(
        "--max-age",
        type=int,
        default=300,
        help="Delete screenshots older than this many seconds (default: 300 = 5 minutes). Follow mode uses ~90s.",
    )
    parser.add_argument(
        "--max-keep",
        type=int,
        default=5,
        help="Never keep more than this many recent screenshots (default: 5). Follow mode uses ~10-12.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Capture exactly one screenshot, print its path, and exit.",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete old screenshots according to --max-age/--max-keep and exit.",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Print the path to the most recent screenshot and exit.",
    )
    parser.add_argument(
        "--open-dir",
        action="store_true",
        help="Open the screenshots folder in Windows Explorer and exit.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Fast follow-friendly preset (~0.65s + large recent buffer). Recommended when Follow Mode is on. AI should then run 'follow grab'.",
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="Ultra low-latency (~0.4s, generous buffer). Best for tight observation. AI agents: use 'follow grab' for stable reads.",
    )
    parser.add_argument(
        "--follow",
        action="store_true",
        help="Enable recent frame ring buffer so an AI can see short motion sequences (circling, dragging, etc.).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="One-shot fresh capture + print live paths (current.png first). Good quick observation hook.",
    )

    args = parser.parse_args()

    if args.open_dir:
        open_screenshots_dir()
        return

    if args.cleanup:
        deleted = cleanup_old(args.max_age, args.max_keep)
        print(f"Cleanup complete. Deleted {deleted} file(s).")
        return

    if args.latest:
        latest = get_latest_path()
        if latest:
            print(latest)
        else:
            print("No screenshots yet. Start the watcher with: py screen_watcher.py")
        return

    if args.once:
        path = capture_screenshot()
        # --once is an explicit capture; always seed recent so the caller gets motion context
        # if they later inspect the ring or run follow grab/stream.
        save_recent_frame(CURRENT_PNG)
        print(f"Captured: {path}")
        print(f"current.png is also ready (always the freshest).")
        print("Recent frame buffer also updated (use 'py screen_watcher.py follow stream' or follow grab).")
        print("Tell me: view the screenshot at " + str(path))
        print("     or: view the screenshot at " + str(CURRENT_PNG))
        return

    if args.live:
        # Fresh capture optimized for real-time observation by the AI
        path = capture_screenshot()
        # Explicit live observation → always contribute to recent ring for motion context.
        save_recent_frame(CURRENT_PNG)
        print(CURRENT_PNG)  # Primary live view — always read this first for "what am I seeing right now"
        for r in get_recent_frame_paths(2):
            if r.exists():
                print(r)
        return

    # Real-time / fast presets for observation
    interval = args.interval
    max_age = args.max_age
    max_keep = args.max_keep
    use_follow = args.follow
    recent_buf = RECENT_BUFFER_SIZE if use_follow else 0

    if args.realtime:
        interval = 0.4
        max_age = 300          # 5 minutes of history (much better for following along)
        max_keep = 40
        use_follow = True
        recent_buf = RECENT_BUFFER_SIZE   # 60
        print("[--realtime] Ultra low-latency for real-time observation (0.4s + generous recent buffer).")
        print("             Use 'follow grab' from the AI for stable multi-frame reads.")

    if args.fast and not args.realtime:
        interval = 0.65
        max_age = 300
        max_keep = 30
        use_follow = True
        recent_buf = RECENT_BUFFER_SIZE
        print("[--fast] Good balance for live visual tracking (~0.65s + large recent buffer).")
        print("          AI agents should use 'py screen_watcher.py follow grab' before reading images.")

    # If the persisted flag is on, we behave as follow even without the flag (so user can say the phrase to me and I start the watcher)
    if is_follow_mode() and not use_follow:
        use_follow = True
        recent_buf = RECENT_BUFFER_SIZE
        # keep user's interval or default to something lively
        if interval > 2.0:
            interval = 0.7

    # Normal (or fast/follow) continuous watching
    watch_loop(interval, max_age, max_keep, follow=use_follow, recent_buffer=recent_buf)


if __name__ == "__main__":
    main()
