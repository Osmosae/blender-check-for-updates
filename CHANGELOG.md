# Changelog

## 1.0.0

- Rename the extension to Release Watcher for Blender Extensions branding
  compliance.
- Mark the extension's existing update-checking behavior as stable.
- Verify one portable extension package across Linux, macOS, and Windows.
- Test the declared minimum Blender version and the current Blender release.
- Harden background-worker shutdown and release-package validation.

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
