# Android feasibility spike

This small app tests whether the existing Python portal client and API can be
packaged inside Android and used by a WebView without a separately hosted
server.

## Result

The spike uses Chaquopy 17.2.0 to package Python 3.14, `httpx`, and
`beautifulsoup4`. On the Android 36 arm64 emulator, it successfully imported
the existing `Test.py` parser and `app.py` API module, parsed a timetable
fixture, and served the existing `/api/session` endpoint through
`app.PortalHandler`. A WebView called that API from an embedded
`ThreadingHTTPServer` bound only to `127.0.0.1` on an OS-assigned port.

The source files are copied into Gradle's generated build directory; the
existing Python files are not duplicated or modified. Cleartext traffic is
permitted only for `127.0.0.1` in this feasibility app. External Schulportal
requests continue to require HTTPS.

## Architecture decision

Continue with an embedded Python backend for the Android app rather than
porting the portal client to Kotlin. The current dependencies install for
Android, the existing parser imports and works, and the actual API handler can
serve a WebView request locally. This removes the largest feasibility risk,
but does not prove that authenticated requests to Schulportal succeed from an
Android device.

This is only the first-step proof, not the finished Android app. It does not
yet serve the existing web UI, support login, or test real portal credentials.
The finished app must stop its embedded server cleanly and verify complete
login/session behavior on device.

## Build and run

Requirements: Android Studio/SDK, JDK 17, and Python 3.14 on the build machine.
Gradle downloads Android and Chaquopy plugins the first time.

```sh
./gradlew :app:assembleDebug
```

The APK is written to
`app/build/outputs/apk/debug/app-debug.apk`. Install it on an emulator or
device. The screen should report Python, `httpx`, and Beautiful Soup versions
and show the existing timetable parser's parsed sample lesson.
