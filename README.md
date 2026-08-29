# Blender Update Checker

A modern Blender extension that checks Blender's official build service for new releases.

## Current behavior

- Manual **Help → Check for Blender Updates** command.
- Automatic checking is optional and disabled by default.
- Automatic checks are delayed by 45–90 seconds and cached for the selected
  daily, weekly, or monthly interval.
- Stable, current-release-series, and daily-build channels.
- Automatic failures are silent. Status and errors remain available in the
  extension preferences.
- The extension opens an official Blender download page; it never installs or
  replaces Blender.

## Installation

- Download blender_update_checker-x.y.z.zip from the Releases page. Do not extract it. Drag the ZIP into Blender and confirm the installation. Alternatively, use Edit → Preferences → Extensions → Install from Disk.
