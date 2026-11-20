# Android app

The Android app packages the existing Python portal client and web UI inside
the APK. At runtime, it starts the Python API server on an OS-assigned port
bound only to `127.0.0.1`, then displays the bundled site in a WebView. No
separately hosted app server or remote web assets are required. Schulportal
itself remains an external service, so signing in and loading live school data
requires an internet connection.

The existing `Test.py`, `app.py`, and `web/` files are inputs to Gradle copy
tasks; they are not duplicated or changed by the Android packaging setup.
Web assets are copied from APK assets into the app's private files directory
before the Python server starts. The WebView is restricted to that local
server, and cleartext traffic is allowed only for `127.0.0.1`. Requests from
the Python backend to Schulportal continue to use HTTPS.

## Build and run

Requirements: Android Studio/SDK, JDK 17, and Python 3.14 on the build machine.
Gradle downloads Android and Chaquopy plugins the first time.

```sh
./gradlew :app:assembleDebug
```

The APK is written to
`app/build/outputs/apk/debug/app-debug.apk`. Install it on an emulator or
device. The app opens the existing web login screen; after signing in, its
requests are handled by the embedded Python API.
