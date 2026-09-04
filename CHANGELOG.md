# Changelog

## 0.3.1

- Ignore an in-flight result when the selected release channel changes and
  immediately check the newly selected channel.
- Retry failed automatic checks after 15 minutes, 30 minutes, and then hourly.
- Recover checks interrupted by a previous Blender shutdown or crash.
- Select the newest release available for the current platform and architecture.
- Improve current-version messaging and release-check regression coverage.

## 0.3.0

- Add optional every-launch, daily, weekly, and monthly automatic checks.
- Add stable, current-release-series, and daily-build channels.
- Add dismissible update notifications to Blender's status bar.
