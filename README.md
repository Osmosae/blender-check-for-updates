# Blender Update Checker

[![CI](https://github.com/Osmosae/blender-check-for-updates/actions/workflows/ci.yml/badge.svg)](https://github.com/Osmosae/blender-check-for-updates/actions/workflows/ci.yml)

A modern Blender extension that checks Blender's official build service for new releases.

Requires Blender 4.2.1 or newer.

## Current behavior

- Manual **Help → Check for Blender Updates** command.
- Automatic checking is optional and disabled by default.
- Automatic checking offers mutually exclusive every-launch, daily, weekly,
  and monthly schedules.
- Every-launch checks run after a 45–90 second delay. Interval schedules keep
  recurring while Blender remains open.
- Failed automatic checks retry after 15, 30, and then at most 60 minutes.
- Stable, current-release-series, and daily-build channels.
- If the channel changes during a check, the outdated result is ignored and the
  newly selected channel is checked instead.
- Available updates appear in Blender's status bar with shortcuts to the
  official download page and extension preferences.
- Status-bar notifications can be dismissed or restored for the reported version or build.
- Automatic failures are silent. Status and errors remain available in the
  extension preferences.
- Interrupted checks are recovered cleanly the next time the extension loads.
- The extension opens an official Blender download page; it never installs or
  replaces Blender.

## Installation

- Download `blender_update_checker-x.y.z.zip` from the Releases page. Do not
  extract it. Drag the ZIP into Blender and confirm the installation.
  Alternatively, use Edit → Preferences → Extensions → Install from Disk.
