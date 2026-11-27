# HomeMonitor Lite for Android (optional viewer)

A tiny full-screen WebView wrapper for the controller's read-only `/lite` page.
It is intended for a controller running **on the same Android device** (for
example, Termux on an old phone), because the app opens
`http://127.0.0.1:8787/lite`.

This is an optional viewer, not the monitoring agent. To monitor an Android
device, use [`agents/android`](../agents/android) and Termux instead.

## What it does

- Hides browser chrome, keeps the screen awake, and shows a retry screen when
  the local controller is unreachable.
- Hides the desktop-only `FULL` link.
- Uses the same HttpOnly session cookie as the `/lite` page.
- Does **not** embed the admin token in the APK. Paste the token once on first
  launch. Do not put a real token in source code, a README, or a shell history.

## Build

Requirements:

- JDK 17
- Android SDK build-tools 34.0.0
- Android platform android-35

```powershell
cd android-lite
.\build.ps1
```

The first build creates a local `keystore.jks` and a random password in
`keystore.password`. Both files are ignored by git. Back them up if you want to
publish updates with the same application identity; never commit them.

The APK is written to `..\dist\HomeMonitorLite.apk`. To use a different
keystore, pass `-Keystore PATH -KeystorePassword PASSWORD`.

## Install on a device

Enable USB debugging, connect the device, and confirm it is visible:

```powershell
adb devices
```

Then either install from the build script:

```powershell
.\build.ps1 -Install -Serial DEVICE_SERIAL
```

or install manually:

```powershell
adb -s DEVICE_SERIAL install -r ..\dist\HomeMonitorLite.apk
adb -s DEVICE_SERIAL shell am start -n com.homemonitor.lite/.MainActivity
```

Replace `DEVICE_SERIAL` with the serial shown by `adb devices`. If only one
device is connected, `-Install` can detect it automatically.

For a one-time automatic login, you can pass the admin token at launch:

```powershell
adb -s DEVICE_SERIAL shell am start -n com.homemonitor.lite/.MainActivity --es token YOUR_ADMIN_TOKEN
```

The app types the token into the page, submits the form, and drops it from
memory. The token is still visible to `adb`/process inspection on the host
while the command runs, so pasting it into the app is usually safer.

## Limitations

- The app is built for the controller on `127.0.0.1:8787`. If the controller
  runs on another machine, open `http://CONTROLLER_IP:8787/lite` in a normal
  browser and use **Add to Home screen** instead.
- It targets Android 5.0+ (API 21), but was only physically tested on an older
  Android device. Treat it as optional and experimental.
- It is read-only. Approve, revoke and settings actions stay in the full
  dashboard.
