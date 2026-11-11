#!/bin/bash
# Double-click to stop Smart Playlist Scheduler and remove it from your login items.
# Your media files and saved schedules are NOT deleted.
LABEL="com.smartplaylistscheduler"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Smart Playlist Scheduler has been stopped and removed from login items."
echo "Saved schedules remain in: ~/Library/Application Support/SmartPlaylistScheduler"
echo "(Delete that folder too if you want to start fresh.)"
read -r -p "Press Return to close..." _
