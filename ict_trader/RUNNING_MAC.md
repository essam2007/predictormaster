# Run the deck on your Mac (beginner steps)

Goal: open the research deck in your browser at **http://127.0.0.1:8077**. Pick **one** of
the two methods below. The UI is pre-built and sample data is pre-loaded, so you'll see the
analytics immediately.

---

## Method A — Easiest (double-click)

1. **Get the code onto your Mac.** On the GitHub page for this branch, click the green
   **Code ▸ Download ZIP**. Double-click the downloaded ZIP to unzip it. Open the unzipped
   folder, then go into the **`ict_trader`** folder.
2. **Install Python** (one time): go to <https://www.python.org/downloads/>, download the
   macOS installer, run it, click through. (Skip if you already have Python 3.)
3. **Start the deck:** double-click **`run-deck-mac.command`** inside the `ict_trader` folder.
   - First time, macOS may say *"cannot be opened because it is from an unidentified
     developer."* Fix: **right-click** the file → **Open** → **Open**. (Only needed once.)
   - A Terminal window opens, installs the app (first run takes ~1 minute), then your browser
     opens to the deck automatically.
4. **Leave that Terminal window open** while you use the deck. To stop, press **Ctrl+C** in it.

---

## Method B — Terminal (two commands)

1. Do steps 1–2 above (get the code, install Python).
2. Open **Terminal** (Cmd+Space → type "Terminal"). Then paste these, replacing the path with
   where your `ict_trader` folder is (tip: type `cd ` then drag the folder into Terminal):

   ```bash
   cd ~/Downloads/predictormaster-*/ict_trader
   python3 -m venv .venv && ./.venv/bin/pip install -e ".[serve]"
   ./.venv/bin/python scripts/run_all.py --no-build
   ```
3. Open **http://127.0.0.1:8077** in your browser.

---

## Method C — Docker (if you have Docker Desktop)

```bash
cd path/to/ict_trader
docker compose up
```
Then open **http://127.0.0.1:8077**. (Builds the UI + API into one container; no Python or
Node needed on your Mac.)

---

## Once it's open
- The deck loads with **sample** data so you can see every tab.
- **Log your real trades:** go to the **Log Trade** tab, paste a control token (set
  `ICT_TRADER_CONTROL_TOKEN` in a `.env` file first; copy `.env.example`), record each
  TradingView paper trade, then switch the top **data** selector to **demo** to watch your
  per-bucket stats build.
- **Connect Tradovate (demo):** put your `TRADOVATE_*` values in `.env`, then the
  **Control ▸ Test Tradovate connection** button (or `./.venv/bin/python scripts/test_tradovate.py`).
- **Don't want the live UI?** `./.venv/bin/python scripts/report.py --mode demo --out report.html`
  makes a single openable HTML report.

## Trouble?
- *"command not found: python3"* → install Python (step 2), then reopen Terminal.
- *Browser shows "can't connect"* → make sure the Terminal window is still running and shows
  `Uvicorn running on http://127.0.0.1:8077`.
- Anything else → tell me the exact message.
