# AI Visual Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

A privacy-first tool that lets AI assistants (Grok, Claude, Cursor, and similar tool-using agents) see your desktop in near real-time.

Screenshots are written to your local disk only. You are always in control. Nothing is ever uploaded to the cloud.

## Features

- **Follow Mode** for real-time visual collaboration (mouse gestures, UI state, debugging, etc.)
- Stable `follow grab` snapshots so AIs can reliably read images without race conditions with rotation
- 1-hour automatic safety timeout for Follow Mode
- Works with Grok, Claude, and other agents that can run shell commands + read local images
- Automatic cleanup for privacy
- Windows-friendly starters + cross-platform Python core

## Installation

```bash
git clone https://github.com/gadalleore/AI_Visual_Assistant.git
cd AI_Visual_Assistant
pip install -r requirements.txt

# Recommended for fast/high-frequency capture (mouse following)
pip install mss
```

See `requirements.txt` for details. mss is ~5x faster than the PIL fallback.

## How it works (the important part)

1. **You** decide when I can see your screen. Run the watcher only when you want the capability.
2. The script saves screenshots locally as PNG files with timestamps.
3. You tell me the path (or "look at my screen" + paste the path).
4. I read the image directly from your disk using my tools (`read_file` on the PNG).
5. After we're done, the file gets deleted (automatically after a few minutes, or manually).

**Nothing is uploaded anywhere.** The images stay on your machine until deleted. I only "see" them when you explicitly give me the path in this chat.

## Quick start

```powershell
# One-time setup
cd path\to\AI_Visual_Assistant
py -m pip install -r requirements.txt

# Basic watcher
py screen_watcher.py

# Recommended for live Follow Mode (mouse circling, gestures)
py screen_watcher.py --fast
# or
py screen_watcher.py --realtime
```

While it's running you will see output like:

```
Captured: /path/to/screenshots/screen_20250410_142301.png
          (current.png also updated)
```

Then tell your AI:

> look at my screen  
> /path/to/screenshots/screen_20250410_142301.png

or (always the newest):

> view the screenshot at /path/to/screenshots/current.png

(The watcher keeps `current.png` updated to the latest shot every time.)

I will use my tools to load and describe exactly what is on the screen, then we can talk about it.

Stop the watcher anytime with **Ctrl+C**.

## Handy one-off commands

```powershell
py screen_watcher.py --once          # one shot, print path
py screen_watcher.py --latest        # print path to newest
py screen_watcher.py --open-dir      # open the screenshots folder
py screen_watcher.py --cleanup       # manual cleanup
py screen_watcher.py follow status
py screen_watcher.py follow stream   # print current + recent paths for the AI
py screen_watcher.py follow grab     # BEST: create stable snapshot for AI
py screen_watcher.py follow instructions
```

See the full list with `py screen_watcher.py --help` and `py screen_watcher.py follow`.

## Files and locations

Screenshots and state live **outside** the project (in your home directory) so they don't pollute the repo:

- **Windows**: `%USERPROFILE%\.ai-visual-assistant\screenshots\`
- **macOS / Linux**: `~/.ai-visual-assistant/screenshots/`

Contents:
- `current.png` — always the latest full capture (overwritten each time)
- `screen_YYYYMMDD_HHMMSS.png` — timestamped full captures
- `recent/frame_*.png` — short ring buffer of recent moments (for motion)
- `grab/` — stable copies created by `follow grab` (safe for AI vision tools)
- `follow_mode.txt` + `follow_mode_started.txt` — state for Follow Mode + 1h safety timer

This design keeps your personal data out of version control.

## Auto cleanup (important for privacy)

- By default: screenshots older than **5 minutes** are deleted on the next capture.
- It also never keeps more than the **5 most recent** files.
- You can change this with `--max-age` and `--max-keep`.
- After a session you can force cleanup with `--cleanup`.

This means after I look at your screen and we finish talking, the evidence disappears automatically.

## Follow Mode (real-time visual following)

See `FOLLOW_MODE_INSTRUCTIONS.txt` (in the repo) or run:

```powershell
py screen_watcher.py follow instructions
```

**Key commands when you tell your AI "Follow Mode On"**:

```powershell
py screen_watcher.py --fast            # or --realtime
py screen_watcher.py follow grab       # create stable snapshot for the AI to read
py screen_watcher.py follow grab --json
py screen_watcher.py follow status
```

The `grab` command is the recommended way for any AI to get reliable visuals.

Full details (including 1-hour auto-off safety, Claude/other agent support, and the ring buffer) are in `FOLLOW_MODE_INSTRUCTIONS.txt`.

## Tips for real-time collaboration

- Use `--fast` (or `--interval 0.6 --follow`) when you want me to follow mouse actions.
- `current.png` is always safe to tell me about — it is the live view.
- For motion, say "look at the recent frames" or just describe — I will pull the ring buffer.
- You can keep the watcher running in a separate terminal the whole time you're working.
- If you have multiple monitors, we currently capture the primary monitor (fast path). We can expand later.

## Privacy & safety

**Only turn this on when you are comfortable with me seeing your entire desktop.**

Screenshots will include:
- Whatever apps and windows you have open
- Filenames, code, documents, browser tabs, emails, etc.
- Potentially passwords if they are visible on screen (never type passwords while this is active)

Best practice: pause or stop the watcher (Ctrl+C) before doing anything sensitive.

## Future ideas (if you want to extend this)

- Hotkey (e.g. Win+Shift+S variant) that triggers a one-shot capture and prints the path
- Optional local HTTP server so a future tool can ask for the "current view" without you copying paths
- Region-only capture (just the active window)
- Support for explicitly choosing which monitor(s)

For now this is deliberately simple, private, and fully under your control.

---

Run it when you want me to see. Tell me the path. I look, advise, and the file goes away.
Enjoy the real-time visual collaboration!
