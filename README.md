# AI Visual Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

A privacy-first tool that lets AI assistants (Grok, Claude, Cursor, and similar tool-using agents) see your desktop in near real-time.

Screenshots are written to your local disk only. You are always in control. Nothing is ever uploaded to the cloud.

## Features

- **Follow Mode** for real-time visual collaboration (mouse gestures, UI state, debugging, etc.)
- **Watcher-free burst grab**: a single `follow grab` fires a short burst of fresh frames (default 5, ~2s) on demand — no continuous background capture needed
- Stable `follow grab` snapshots so AIs can reliably read images without race conditions with rotation
- Grab area is self-pruning — repeated grabs will not cause unbounded growth
- 1-hour automatic safety timeout for Follow Mode
- Resilient capture: automatic runtime fallback from the fast `mss` backend to PIL, plus watcher recovery from transient display/driver glitches (won't just die)
- Automatic bounded garbage collection (main screenshots + recent ring + stable grab snapshots) so your `~/.ai-visual-assistant` folder stays under control even with heavy one-shot or AI-driven use
- Works with Grok, Claude, and other agents that can run shell commands + read local images
- Windows-friendly starters + cross-platform Python core

## Installation

### From source (recommended)

```bash
git clone https://github.com/gadalleore/AI_Visual_Assistant.git
cd AI_Visual_Assistant

# Modern recommended way (uses pyproject.toml)
pip install -e .                    # basic editable install
pip install -e ".[fast]"            # includes the faster mss backend

# Classic / legacy route (uses setup.py)
python setup.py develop

# Explicit requirements (if you prefer this style)
pip install -r requirements.txt
```

**What you get:**
- The `screen-watcher` console command (if your Python Scripts folder is on PATH)
- `import screen_watcher` works
- All three packaging options are provided so users can choose what they prefer

### One-off usage (no installation at all)

```powershell
py -m pip install -r requirements.txt
py screen_watcher.py --fast
```

### Packaging files (we provide all three for maximum flexibility)

- `pyproject.toml` — modern standard (PEP 621). This is the preferred file for new installs, dependency declaration, and the `screen-watcher` entry point.
- `setup.py` — thin backwards-compatible shim. Lets `python setup.py develop`, very old tools, and `pip install -e .` continue to work.
- `requirements.txt` — kept because some people like explicit, copy-paste friendly lists.

After any of the install methods above you can run:

```powershell
screen-watcher --help
# or, if the command isn't in PATH yet:
py -m screen_watcher --help
```

### For maximum speed (mouse following / real-time)

The optional `mss` backend is ~5× faster than pure PIL for repeated captures:

```bash
pip install "ai-visual-assistant[fast]"
# or manually
pip install mss
```

Use `--fast` or `--realtime` flags (or the `follow grab` command when working with an AI).

## How it works (the important part)

1. **You** decide when I can see your screen. Run the watcher only when you want the capability.
2. The script saves screenshots locally as PNG files with timestamps.
3. You tell me the path (or "look at my screen" + paste the path).
4. The AI reads the image directly from your disk using its vision tools (e.g. `read_file` on the PNG).
5. After you're done, the file gets deleted (automatically after a few minutes, or manually).

**Nothing is uploaded anywhere.** The images stay on your machine until deleted. The AI only "sees" them when you explicitly give it the path.

## Quick start (after installation)

```powershell
# Basic watcher
screen-watcher
# or
py -m screen_watcher

# Recommended for live Follow Mode (mouse circling, gestures, real-time observation)
screen-watcher --fast
# or
screen-watcher --realtime
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

The AI will use its vision tools to load and describe exactly what is on the screen, then you can talk about it.

Stop the watcher anytime with **Ctrl+C**.

## Handy one-off commands

```powershell
py screen_watcher.py --once          # one shot, print path
py screen_watcher.py --latest        # print path to newest
py screen_watcher.py --open-dir      # open the screenshots folder
py screen_watcher.py --cleanup       # manual cleanup
py screen_watcher.py follow status
py screen_watcher.py follow stream   # print current + recent paths for the AI
py screen_watcher.py follow grab     # BEST: burst of 5 fresh frames -> stable snapshot for AI
py screen_watcher.py follow grab 3   # same, but override the burst count
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
- `grab/` — stable copies created by `follow grab` (safe for AI vision tools; automatically pruned on each new grab to stay bounded)
- `follow_mode.txt` + `follow_mode_started.txt` — state for Follow Mode + 1h safety timer

This design keeps your personal data out of version control.

## Auto cleanup (important for privacy)

The tool is designed to never let screenshot folders grow without bound:

- **When a watcher is running** (`--fast`, `--realtime`, or plain): uses the configured `--max-age` / `--max-keep` (defaults 5 min / 5 files in normal mode; more generous in follow mode).
- **Opportunistic cleanup on every capture**: even one-shot commands (`--once`, `follow grab`, `follow live`, etc.) trigger a loose safety cleanup (4 hours or 300 files by default). This prevents accumulation if you mostly use grab/live without a long-running watcher.
- **Burst grab keeps ONLY the current batch** (privacy + disk): each `follow grab` deletes the *previous* burst's frames — it trims the recent ring to just the new burst and wipes the raw `screen_*.png` captures. At any moment only ~the latest batch (current.png + the burst + their stable grab copies) is on disk; the prior five are gone the instant you grab again.
- **Recent ring buffer** (`recent/frame_*.png`): when a continuous watcher is running it self-trims to ~60 frames; on-demand burst grabs trim it to just the current burst.
- **`grab/` stable snapshots**: the watcher deliberately does *not* touch grab/ (so the AI has stable files), but `follow grab` itself automatically prunes old `grab/recent/` frames and very old grab files after each new snapshot (keeps ~150 recent frames + 2-day age by default). Repeated AI use of "follow grab" will no longer cause the folder to balloon.
- Full manual wipe: `py screen_watcher.py follow cleanup` (or `--cleanup`).

You can still tune the live watcher behavior with `--max-age` / `--max-keep`. After any session you can force a total cleanup.

This means after I look at your screen and we finish talking, the evidence disappears automatically — and long-term usage stays tidy.

## Follow Mode (real-time visual following)

See `FOLLOW_MODE_INSTRUCTIONS.txt` (in the repo) or run:

```powershell
py screen_watcher.py follow instructions
```

**Key commands when you tell your AI "Follow Mode On"**:

```powershell
py screen_watcher.py follow grab       # burst of 5 fresh frames -> stable snapshot
py screen_watcher.py follow grab --json
py screen_watcher.py follow grab 3     # override burst count
py screen_watcher.py follow status
py screen_watcher.py --fast            # OPTIONAL: continuous watcher for fine motion following
```

The `grab` command is the recommended way for any AI to get reliable visuals. It now
captures its own fresh burst on each call, so **no continuous watcher is required** for the
normal "look at where I am now" loop — start `--fast`/`--realtime` only if you specifically
want continuous real-time motion following.

**Real-time note interaction rule:** When you communicate by writing on an on-screen note (sticky note, etc.), the AI should give **only 2-3 sentences at a time**. If no new question appears on the screen, the AI should simply repeat its previous 2-3 sentences until you provide new input. This keeps the interaction paced with your typing. See `FOLLOW_MODE_INSTRUCTIONS.txt` for the full rule the AI is instructed to follow.

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
