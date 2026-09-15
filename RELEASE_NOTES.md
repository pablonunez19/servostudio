Servo Studio v0.2.0 preview

New in this release:
- Live slider movement: changes retarget the servo immediately without a backlog.
- Typed angles move after one second of inactivity. Move now sends immediately.
- Stop invalidates late live requests; live control cannot interrupt another tab or a sequence.
- Set to current position buttons for Minimum, Maximum and Center read the encoder and apply that setting. Saving to flash remains separate.

Download the archive for your operating system, extract it fully, and launch ServoStudio. macOS users choose Apple Silicon (arm64) or Intel (x64). Windows and Linux builds are x64. The launcher opens the authenticated local browser panel automatically; no Python installation is needed.

The app waits for Connect servo before opening the serial device. Use --simulate to try it without hardware. Quit Servo Studio in the browser shuts down the local server. The default port is 8108; if occupied, the app chooses a free localhost port and opens that exact address.

Includes named positions, hardware configuration with read-back, motion sequences, profiles, and simulation. Settings persist in your operating system's user-data directory, outside the app bundle.

This is a prerelease. The original macOS hardware controller was physically tested with a DPC-20 and MDB961/SER-2131. The portable serial implementation and Windows/Linux hardware behavior need device validation. All release platforms run automated tests and an actual packaged HTTP/simulation smoke test before publishing.

Builds are not publisher-signed or Apple-notarized. Operating systems may display an unrecognized-publisher warning or block first launch. No driver installation is bundled; the DPC-20 must appear as a serial port, and Linux users need serial-device access. Firmware updates, multiple servos and additional operating modes are not included.
