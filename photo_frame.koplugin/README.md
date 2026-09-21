# Photo frame KOReader plugin

This is a deliberately narrow Kindle photo-frame experiment for KOReader’s Kindle
platform: local images, airplane mode, a scheduled maintenance wake, one full-screen
refresh, and no network activity. It has been personally tested on the Paperwhite 3
and first-generation Scribe; other KOReader-supported Kindles remain untested.

## Install

For the download-and-copy walkthrough, see the
[beginner guide](https://github.com/kuslota/kindle-photo-frame#install-the-plugin).
Copy this folder to `koreader/plugins/photo_frame.koplugin`, and supported image
files (or prepared JPG/PNG exports) to `koreader/photo_frame/images`. Restart KOReader, then use
**Tools → Photo frame → Change photo every** (2 minutes for the initial test),
and **Start photo frame and sleep now**. After several photo changes, use 15 minutes
or longer and enable airplane mode.

The default interval is 15 minutes. The editable field accepts whole minutes
from 2 through 1440; the two-minute minimum leaves enough time for the Kindle
to reach `ReadyToSuspend` before its RTC alarm expires. Runtime state is
stored in `koreader/settings/photo_frame.lua`; measurements are appended to
`koreader/photo_frame/photo_frame.tsv`.

## Important behavior

- The plugin uses `Device.wakeup_mgr:addTask`. On Kindle this is bridged through
  powerd/LIPC during `ReadyToSuspend`; it does not write `/dev/rtc0` directly.
- A scheduled Kindle wake remains inside the sleep-screen state. The callback
  redraws the existing KOReader `ScreenSaverWidget`, queues the next wake, and
  returns to powerd. It intentionally does **not** call the power-button toggle
  again.
- A real user resume removes the pending maintenance task. The next normal
  suspend redraws a photo and starts a fresh configured interval. Changing the
  interval while enabled also replaces the pending wake task immediately.
- The shuffled playlist and next index are flushed after every selection, so a
  KOReader restart does not reset the sequence.
- Wi-Fi is never enabled or queried by this plugin.

## Logs

Optional **Diagnostic logging** is disabled by default. When enabled from
the plugin menu, `photo_frame.tsv` contains these tab-separated fields:

```text
timestamp event image render_ms battery_percent note
```

Expected events include `suspend`, `wake`, `rendered`, `wake_scheduled`, and
`return_to_suspend`. `return_to_suspend` is the time at which the callback
hands control back to Kindle powerd; it is not a claim that the kernel has
already completed suspend.

The active log rotates to `photo_frame.tsv.old` at 256 KiB, so diagnostic
logging is bounded even when left enabled. Disabling logging stops TSV battery
reads and writes, as well as routine events in KOReader’s `crash.log`.
Warnings and errors still use KOReader’s normal log. Existing TSV files may be deleted safely while KOReader is
stopped or the Kindle is mounted over USB.

## Stop or recover

Wake the Kindle normally and uncheck **Automatically change photos**. If the UI
cannot be reached, remove the plugin folder over USB and restart KOReader. No
system files, launch scripts, or network settings are modified.

## Compatibility boundary

The implementation was checked against KOReader source commit
`03fe3be9adaabebaef85f0c13094414662fde600` (2026-08-21). KOReader identifies
the first-generation Scribe as `KindleScribe`; it uses the same Kindle
`powerd`/`WakeupMgr` abstraction as the PW3. The plugin reads framebuffer width
and height from KOReader at runtime, so the plugin code is shared and only the
preprocessed image profile changes.

Test on the exact KOReader build, Kindle model, and firmware before relying on
it unattended. Kindle powerd timing is firmware-sensitive; the callback is
normally dispatched about 15 seconds into a maintenance wake because KOReader
filters early/user wakes. Passing the PW3 bench test does not substitute for a
separate Scribe suspend/RTC bench test.
