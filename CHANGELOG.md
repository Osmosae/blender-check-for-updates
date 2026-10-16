# Changelog

## 1.3.0

- Reject malformed or inconsistent build-feed records before selecting an update.
- Validate requests and results exchanged with the background checker, and
  centralize its process lifecycle.
- Keep package verification aligned with the extension manifest and simplify
  Blender setup across CI platforms.

## 1.2.0

- Fall back to Blender's official download table when its JSON feed is broken.
- Ignore checksum files when selecting a downloadable build.
- Follow newer alpha, beta, and RC builds within Current Release Series when
  running a prerelease, without jumping to the next development series.
- Compare commit identity and commit time for same-version development builds
  and recognize beta/RC-to-final updates without a version-number change.
- Keep Daily Builds following the newest development series and clarify this
  behavior in preferences.

## 1.1.0

- Keep the delayed automatic-check timer alive while Blender loads its startup
  or project file, so every-launch checks actually run.
- Preserve full timestamp precision and display seconds so completed launch
  checks reliably update the visible last-check time.

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
