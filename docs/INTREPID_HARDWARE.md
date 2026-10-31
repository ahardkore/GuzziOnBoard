# Intrepid Control Systems hardware

This is an adapter integration, **not** a new motorcycle ECU protocol, memory
reader or flash implementation. It uses the existing GuzziOnBoard CAN ISO-TP
sessions and their profile, mode and programming gates. No Intrepid hardware or
motorcycle has been tested by GuzziOnBoard: tests use a simulated Intrepid API
with the actual python-can neoVI backend. Electrical wiring, channel wiring,
selected vehicle, CAN speed and ECU protocol still need to match. The adapter
may acknowledge traffic and opening it can change its configured bitrate.

## Source-run desktop: direct neoVI / ValueCAN

1. Install the Intrepid-supplied driver/runtime appropriate for the specific
   hardware and operating system. The vendor reports Windows requires
   `icsneo40.dll` installed on PATH; Linux and macOS wheels carry a
   `libicsneolegacy` library. Follow the vendor's current instructions;
   compatible devices and platform dependencies vary. No driver or DLL is
   downloaded or installed by GuzziOnBoard.
2. In the Python environment used to run the desktop application, install the
   optional dependencies:

   ```sh
   python -m pip install -e '.[desktop,hardware,intrepid]'
   guzzionboard-desktop
   ```

   Windows shells may use `py -m pip` and `py -m guzzionboard.desktop`.
   Restart the application after installing. The python_ics wheel can depend on
   additional vendor services, drivers and system libraries; successful import
   does not prove the device can be opened.
3. Select a compatible CAN profile and **CAN (ISO-TP)**, then choose **Intrepid
   neoVI / ValueCAN (source-run Python)**. Enter the actual device serial and
   exactly one CAN network name (e.g. `HSCAN`, `HSCAN2`, `MSCAN`, `DWCAN_01`)
   or its supported decimal network ID in the Device field. The application
   refuses an unspecified serial, multiple networks and non-CAN network IDs;
   it will not automatically pick the first device. IDs are the Intrepid
   network IDs, not an ECU's CAN request/response IDs.
4. Check request/response IDs, profile-specific bitrate, read-only mode,
   wiring and the connection checklist. The python-can backend sets the
   selected CAN network's bitrate to the profile value; this may alter adapter
   configuration. Connecting a diagnostic profile sends its documented
   application requests and may transmit ISO-TP flow-control frames. This is
   **not** a silent bus observer or a way to enable ECU writing.

The direct backend is available when running from a Python environment with
`python_ics`. **Standard packaged desktop builds do not bundle python_ics or
its vendor native libraries**, and installing it in system Python does not
add it to a frozen executable. On Linux the packaged app can instead use an
externally configured SocketCAN interface as described below. No direct
neoVI path is claimed for standard frozen Windows/macOS builds.

## Existing Linux SocketCAN path

Intrepid's [icsscand](https://github.com/intrepidcs/icsscand/tree/4a38ebda34e88dfc02ff24c76f07aaaf7e2bb530)
requires its separately installed kernel module and dependencies, then exposes
CAN interfaces. Install and run those separately following the vendor's
instructions; GuzziOnBoard does not build them, run commands with privileges,
configure interfaces, or install drivers. Confirm the interface alias, device,
network, wiring, bitrate and interface state externally. Choose the default CAN
backend in GuzziOnBoard and enter the resulting `canN` interface name. The
existing broadcast observer can also use an appropriate SocketCAN interface.
Controller listen-only mode must be configured separately if required. No
SocketCAN/Intrepid combination has been physically tested by this project.

## Sources and licenses

- [python_ics, revision 89e69b0d](https://github.com/intrepidcs/python_ics/tree/89e69b0d2d3c69fa296462dfb9b1e306b7a81819) is MIT-licensed; its README describes platform prerequisites. We use it as an optional separately installed dependency, not a bundled source copy.
- [libicsneo, revision 5c61a3b3](https://github.com/intrepidcs/libicsneo/tree/5c61a3b3c1d6a38c89cdf9c47fced7cf9eb1da4e) has a BSD-like license **with an additional restriction prohibiting use with non-Intrepid vehicle-network hardware**. The current python_ics Linux/macOS build source pins libicsneo `0dd8dbf` and supplies a native library in wheels. Check the actual installed version and its terms; the extra condition is not standard BSD or MIT. Standard GuzziOnBoard builds do not distribute this library.
- [icsscand, revision 4a38ebda](https://github.com/intrepidcs/icsscand/tree/4a38ebda34e88dfc02ff24c76f07aaaf7e2bb530) has a BSD-2-Clause daemon and links a separately licensed libicsneo submodule. Its kernel driver has its own terms and requirements.
- [Intrepid neoVI API documentation](https://github.com/intrepidcs/neoVI_API_Docs/tree/394da3fea30e5471ac7489876786992769b32cd4) and the [older archived icsneoapi](https://github.com/intrepidcs/icsneoapi/tree/b73fa55a03ce35f2bccebf2270a2e12e3dfaa529) describe general device APIs, not motorcycle-specific flash algorithms. libicsneo has ISO9141/ISO14230 and J1850 network types, but this integration implements **CAN only**; an API enum is not a verified K-Line/J1850 initialization or ECU programming sequence.
