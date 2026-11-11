# Smart Playlist Scheduler

Schedule images and videos to appear in (and disappear from) a **ProPresenter Smart Playlist** automatically.

A ProPresenter Smart Playlist mirrors a folder on your Mac: whatever is in the folder shows up in the playlist.
This app moves files from a **Media library** folder into that **Smart Playlist folder** at a time you choose,
and moves them back out when the time is up. You set everything up by pointing and clicking in your web browser.

- **One-time schedules**: e.g. *Sunday Nov 15, 8:00 AM to 1:00 PM*
- **Weekly schedules**: e.g. *every Saturday & Sunday, 8:00 AM to 1:00 PM*
- **Quiet hours**: no files move during service; moves that come due wait until quiet hours end
- **Catches up**: if the Mac was asleep at a scheduled time, the move happens as soon as it wakes
- **Safe**: never overwrites or deletes files; files without a schedule are never touched

## Install (Mac)

1. On the ProPresenter Mac, click the green **Code** button on this GitHub page, then **Download ZIP**.
   Unzip it and move the folder somewhere permanent (e.g. your Documents folder).
2. Open the folder and **right-click `Install.command` → Open** (the first time, macOS asks
   you to confirm because it was downloaded from the internet). A Terminal window will run the setup.
   - If Python isn't installed yet, macOS will offer to install the *Command Line Developer Tools*.
     Click **Install**, wait for it to finish, then run `Install.command` again.
3. Your browser opens to **http://localhost:8765**. The app now starts automatically whenever you log in.
   To get back to it later, double-click `Open Scheduler.command` or bookmark the address.

## Set up ProPresenter

1. Create two folders, for example:
   - `Documents/Playlist Media/Library`: all your promo images and videos live here
   - `Documents/Playlist Media/Live`: the scheduler puts files here while they're "on"
2. In ProPresenter, create a **Smart Playlist** that points at the **Live** folder.
3. In the scheduler, click **Choose…** next to each folder and pick them.
4. Click any file in the Library to schedule it.

> **Test first:** copy a file into the Live folder by hand and check how quickly it appears in your
> Smart Playlist. That's how quickly scheduled changes will appear too.

## Tips

- Use **Quiet hours** (under Folders) to block changes while ProPresenter is live, so a file is never
  pulled out of the playlist while it's on screen.
- Deleting a schedule doesn't delete the file. If the file was in the playlist, it goes back to the Library.
- One-time schedules are cleaned up automatically a week after they finish.
- Don't put a file with the same name in both folders; the app will refuse to move it and say so in **Activity**.

## Troubleshooting

| Problem | Fix |
|---|---|
| Activity says **"Operation not permitted"** | macOS is blocking access to the folder. Open **System Settings → Privacy & Security → Full Disk Access** (or **Files and Folders**), click **+**, press **⌘⇧G**, and add the Python path that `Install.command` printed (e.g. `/usr/bin/python3`). Then run `Install.command` again. |
| Browser says it can't connect | Run `Install.command` again. Logs are in `~/Library/Logs/SmartPlaylistScheduler/`. |
| Moved the app folder | Run `Install.command` again from the new location. |

To remove the app, double-click `Uninstall.command`. Your media and saved schedules are kept
(schedules are stored in `~/Library/Application Support/SmartPlaylistScheduler/`).

## For developers

Plain Python 3.8+ standard library, no dependencies.

```bash
python3 app/server.py --open                 # run in the foreground
python3 -m unittest discover -s tests        # run the tests
```

Environment variables: `SPS_PORT` (default 8765), `SPS_HOST` (default 127.0.0.1, so it is local-only),
`SPS_DATA_DIR`.

The scheduler is state-based: every 30 seconds it works out which scheduled files *should* be in the
Live folder right now and moves any that are in the wrong place (see `app/scheduler.py`).
