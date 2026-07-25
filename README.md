# Roadmap

## 1. What it does

The tool searches Jira epics by keyword — checking both the epic name and summary — and collects every task belonging to matched epics. It then builds an Excel report with three tabs: tasks, summary, and weekly.

Keyword matching works best with a consistent epic naming convention. The keyword becomes the **Feature** name, and everything after the colon becomes the **Substream**.

For example, keyword `Checkout Redesign` collects all of these epics at once:
- Checkout Redesign: Scope definition
- Checkout Redesign: Payments
- Checkout Redesign: Mobile polish

And produces rows like this in the tasks tab:

| Feature | Substream | Task type | Task | Status | Start | End | Done week | ETA | Days in work | Δ ETA |
|---|---|---|---|---|---|---|---|---|---|---|
| Checkout Redesign | Scope definition | Task | Backend: Refactor cart schema | done | 03.Mar.26 | 14.Mar.26 | 11 | 16.Mar.26 | 8 | −2 |
| Checkout Redesign | Payments | Task | Payments API: Multi-currency support | in progress | 10.Mar.26 | | 12 | 16.Mar.26 | 14 | +5 |
| Checkout Redesign | Mobile polish | Task | Define mobile checkout flow | | | | | 16.Mar.26 | | |

> To track delivery date for an epic independently, use the full epic name as a separate keyword: `Checkout Redesign: Payments`.

---

### What can be used as a keyword

- **Any word the epic contains** — `Checkout Redesign` matches any epic whose name or summary includes that text
- **The full epic name** — `Checkout Redesign: Payments` targets that one epic precisely
- **The epic's Jira key** — e.g. `PROJ-1234`. Targets that exact epic; the feature name in the report will be the epic's actual name, not the key

### When keywords overlap

If you track both a broad keyword and a more specific one it contains, the more specific keyword wins for any epic it matches — everything else still falls under the broader one.

For example, tracking both `Checkout Redesign` and `Checkout Redesign: Payments` creates two separate features:
- **Checkout Redesign: Payments** — epics matching the more specific keyword
- **Checkout Redesign** — every other epic that only matches the broader keyword

### Excluding keywords

You can also exclude keywords. Any epic matching an excluded keyword is dropped from the report entirely, regardless of what else it matches.

For example, if `Checkout Redesign` pulls in `Checkout Redesign: post-release` and you don't want that skewing your pace and ETA, exclude `post-release` and it's gone.

---

### Feature status filter

The tasks tab has a built-in table filter on the **Feature status** column. By default it hides features that aren't actively in progress — you can show or hide any status directly through the filter in Excel or Google Sheets:

| Status | Meaning |
|---|---|
| **done** | All tasks in the feature are done or rejected |
| **on hold** | Some tasks are done or rejected, but remaining ones are not in progress |
| **open** | All tasks have an empty status — nothing started yet |

Features with at least one task in progress are shown by default.

---

### How Jira statuses are mapped

Jira's many statuses are simplified into four values:

| Display | Jira statuses |
|---|---|
| *(no status)* | Backlog, To Do, Open, and anything else not listed below |
| **in progress** | In Progress, In QA *(any variant)*, Code Review, Progress Done |
| **done** | Done, QA Prod Done, In Validation |
| **rejected** | Rejected |
| **on hold** | QA On Hold, Track/Blocked/On Hold |

**Done statuses are configurable.** By default, `Done`, `QA Prod Done`, and `In Validation` all count as done. If a status like `In Validation` means active work is still happening in your team, you can remove it during setup or by editing `done_statuses` in your local settings file.

When a task goes on hold after being in progress, the report splits it into separate rows — one per active period, one per pause. Time spent on hold is excluded from *days in work*, so pauses don't inflate the count.


---

## 2. Summary tab

Shows one row per feature and estimates when it will be delivered:

- **You provided an expected pace** → ETA = remaining tasks ÷ expected tasks per week
- **You provided a deadline** → calculates the required pace to hit it and compares against actual
- **Neither** → approximates delivery date from the actual pace observed in recent weeks


---

## 3. Weekly tab

Shows a week-by-week breakdown for one feature at a time. Use the dropdown in cell A2 to switch features.

Each week shows tasks closed (done + rejected) vs tasks created:
- 🔥 **Burning** — more closed than created, scope is shrinking
- 🚀 **Growing** — more created than closed, scope is expanding

If you set a deadline, the **Required** column shows the pace needed each week to deliver on time, so you can compare it against what's actually happening.

*(screenshot — weekly tab)*

---

## 4. How to set up

### Requirements

| What | Mac | Windows |
|---|---|---|
| **Python 3** | Installed automatically — macOS prompts to install it the first time you run the tool, no action needed | Install yourself from [python.org/downloads/windows](https://www.python.org/downloads/windows/) before running the tool |

Nothing else to install — Jira setup just asks for your Jira URL and Personal Access Token directly.

**Windows note:** Windows support exists in the same sense that a treaty exists — it's written down, everyone means well, and it has never survived contact with reality. It works *theoretically*. Nobody has actually run it on a real Windows machine yet, so genuinely, expect anything: it might work perfectly, it might ask you to `sudo chown` your own `C:\`, it might achieve sentience. If you're on Windows and feeling brave, please try it and tell us what breaks — see "If something goes wrong" below for how to send us the evidence.

### Jira connection

The first time you run the tool, if Jira isn't configured on your computer yet, it will open a guided setup automatically. You'll need:

| What | Where to get it |
|---|---|
| **Jira URL** | Your company's Jira address, e.g. `track.yourcompany.com` |
| **Personal Access Token** | In Jira: click your avatar → Profile → Personal Access Tokens → Create |

### Settings file

All settings are stored in `settings/roadmap-settings.local.json`. This file is yours — it stays on your computer and is never shared.

The first time you run the tool, if the file doesn't exist yet, it will ask you a series of questions and create it automatically — setup is fully guided, just answer the prompts.

You can edit this file at any time in any text editor to change settings without going through setup again, or run the `edit` command from the tool.

The repo also includes `settings/roadmap-settings.json` — an empty template for distribution. When a colleague downloads the folder, the tool seeds their local file from this template on first run.

---

## 5. How to use

The tool works on both Mac and Windows.

- **Mac/Windows** — double-click `jira-report/roadmap`

A terminal window opens and walks you through the rest.

> **Mac: first-run security warning.** Since `roadmap` is a downloaded, unsigned script, macOS Gatekeeper will block it the first time with a message like *"roadmap" can't be opened*. To allow it:
> 1. Try to open `roadmap` once so macOS registers the block.
> 2. Open the Apple menu () → **System Settings**.
> 3. Click **Privacy & Security** in the sidebar, then scroll down to the security section.
> 4. Find the message about `"roadmap"` being blocked and click **Open Anyway**.
>
> You only need to do this once.

### Google Drive

If you want the report uploaded to Drive so teammates can view it, choose that during setup. You'll be asked for:
- Whether to sync to Google Drive (y/n)
- The Google Drive folder URL
- A Google OAuth client secrets JSON — the tool explains exactly how to create one from Google Cloud Console during setup

### Automatic updates *(Mac only)*

After the first successful run, the report updates automatically every day at the time you chose during setup. If you want to change the time, edit `update_time` and `update_timezone` in your local settings file — no reinstall needed.

Your computer must be on and connected to VPN at the scheduled time for the update to run.

If the report didn't update — because the computer was off or not on VPN — you'll get a notification the next time you open your computer with a **Try Again** button.

### Commands

When you open the tool and a report already exists, it asks what to do:

| Command | What it does |
|---|---|
| `update` | Refreshes all features |
| `update checkout redesign` | Refreshes only the feature named exactly *Checkout Redesign* |
| `update all checkout redesign` | Refreshes every feature whose name contains "checkout redesign" — e.g. *Checkout Redesign*, *Checkout Redesign: Payments*, *Checkout Redesign: Mobile polish* |
| `new` | Starts setup from scratch with new keywords |
| `edit` | Opens the keyword editor to add or remove features |
| `quit` | Closes without doing anything |

---

## 6. If something goes wrong

If the tool hits an unexpected error, it saves a log file to `roadmap-crash-log.txt` in your home folder and tells you the exact path. Send that file along with a short description of what you were doing — that's enough to debug most issues without needing to reproduce them.
