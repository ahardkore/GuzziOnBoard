/* GuzziOnBoard help knowledge base — content only.
 *
 * This file holds every word the Help & Reference module shows: the how-to
 * guides, the per-tool manual, the wire-protocol reference, checksum and XDF
 * theory, the safety-gate explanations and the glossary. It is deliberately a
 * plain data file with no logic so it can be reviewed like documentation, and
 * so web/help-module.js can index the same text for global search.
 *
 * Conventions
 *   id         stable slug, used in the shareable URL #help/<id>
 *   category   one of the ids in `categories` below
 *   tags       extra words the search box should match
 *   body       trusted HTML authored in this file (never user input)
 *   tools      jump buttons: { label, view, selector?, openDetails? }
 *
 * Dynamic sections — the ECU catalog, the bundled XDF library and the workshop
 * tool directory — are generated at run time by help-module.js from /api/catalog,
 * /api/maps and the `tools` array declared here.
 */
(function () {
  'use strict';

  const CATEGORIES = [
    { id: 'howto', label: 'How-To Guides', blurb: 'End-to-end, numbered workflows: connect, log, back up, edit, build, write.' },
    { id: 'tools', label: 'Every Tool & View', blurb: 'Every workspace, panel, dialog and workshop utility in the program.' },
    { id: 'protocols', label: 'Protocols & Buses', blurb: 'K-Line, KWP2000, ISO 9141, CAN/ISO-TP, J1850 VPW, TTL serial, multicast.' },
    { id: 'ecus', label: 'ECUs & Catalog', blurb: 'ECU families, capability levels, memory geometry and the bundled catalog.' },
    { id: 'checksums', label: 'Checksums & XDF', blurb: 'Frame vs calibration checksums, providers, XDF math, flags, patches, floats.' },
    { id: 'safety', label: 'Safety & Troubleshooting', blurb: 'The write gate, acknowledgements, tokens, recovery plans and common failures.' },
    { id: 'glossary', label: 'Glossary', blurb: 'Plain-language definitions of every ECU, tuning and workshop term used here.' },
  ];

  /* Which manufacturer (or family) a tool belongs to. Mirrors the brand
   * <select> on the Tools bench: 'general' means it works on any motorcycle
   * or needs no bike at all. Keep both lists in step - tests/test_help_module.py
   * compares them with the data-tool-brand attributes in web/index.html. */
  const BRANDS = [
    { id: 'general', label: 'General', note: 'works on any motorcycle, or needs no bike at all' },
    { id: 'aprilia', label: 'Aprilia', note: 'IAW 15P / 5AM / 7SM and MIU G3 definitions', oem: true },
    { id: 'bajaj', label: 'Bajaj', note: "RS200 Dell'Orto image checksum research", oem: true },
    { id: 'bmw', label: 'BMW Motorrad', note: '11-bit CAN broadcast frames', oem: true },
    { id: 'buell', label: 'Buell', note: 'DDFI / DDFI-2 / DDFI-3 serial and EEPROM', oem: true },
    { id: 'cfmoto', label: 'CFMoto', note: 'Bosch MSE6 offline record research', oem: true },
    { id: 'ducati', label: 'Ducati', note: 'Panigale Mitsubishi CAN layout', oem: true },
    { id: 'harley', label: 'Harley-Davidson', note: 'Delphi J1850 / CAN, Power Vision and Centurion files', oem: true },
    { id: 'honda', label: 'Honda', note: 'Keihin PGM-FI frames and source-ID checksums', oem: true },
    { id: 'husqvarna', label: 'Husqvarna', note: 'Keihin KMSK16 KWP2000 identifiers (shared with KTM)', oem: true },
    { id: 'indian', label: 'Indian', note: 'J1939 broadcast PGNs', oem: true },
    { id: 'kawasaki', label: 'Kawasaki', note: 'KDS K-Line identifiers and local IDs', oem: true },
    { id: 'ktm', label: 'KTM', note: 'Keihin KMSK16 KWP2000 identifiers and routines', oem: true },
    { id: 'moto-guzzi', label: 'Moto Guzzi', note: 'IAW 5AM image geometry and definition fit', oem: true },
    { id: 'suzuki', label: 'Suzuki', note: 'SDS K-Line all-sensors answer', oem: true },
    { id: 'triumph', label: 'Triumph', note: 'K-Line ISO 9141 mode 01 frames', oem: true },
    { id: 'yamaha', label: 'Yamaha', note: 'MT image checksum and dashboard stream observation', oem: true },
    { id: 'britek', label: 'BRT Juken', note: 'aftermarket Juken 5 map blocks' },
    { id: 'dynojet', label: 'Dynojet / dyno', note: 'JetDrive telemetry, not an ECU connection' },
    { id: 'rusefi', label: 'rusEFI', note: 'aftermarket controller, .ini definitions and serial pages' },
  ];


  /* ======================================================================
   * TOOLS — every view, panel, dialog and workshop utility.
   * help-module.js turns each entry into a searchable article at
   * #help/tool/<id> with a "jump to it in the program" button.
   * ==================================================================== */
  const TOOLS = [
    /* ---------------------------------------------------- workspace views */
    {
      id: 'view-garage', name: 'Garage — vehicle selection & ECU link', category: 'link',
      view: 'garage', selector: '#connectionPanel',
      summary: 'Choose the motorcycle, the transport (simulator, K-Line, CAN, ELM/J1850 or TTL serial), the adapter and the initialisation method, then connect.',
      steps: [
        'Pick Make, Model and Year in 1 · Motorcycle. The workstation resolves the ECU profile and prints which protocol it speaks.',
        'If a model year has overlapping ECU fitments, use the ECU override dropdown and match the label on the physical ECU.',
        'In 2 · Connection choose the transport, then the serial device (e.g. /dev/ttyUSB0 or COM3) or CAN channel (can0).',
        'Choose the init method only when the profile allows a choice: profile default, automatic, fast init or 5-baud.',
        'Work down the safety checklist; Connect enables once the mandatory rows are acknowledged.',
      ],
      caution: 'A cable never unlocks an unsupported ECU. Research-only profiles refuse connection or offer read-only live data by design.',
      tags: ['connect', 'select', 'transport', 'device', 'init', 'checklist', 'simulator', 'kline', 'can'],
    },
    {
      id: 'view-overview', name: 'Overview — identity, link and capabilities', category: 'link',
      view: 'overview', selector: '#identityPanel',
      summary: 'The ECU identification report, the negotiated link, and a capability grid showing exactly what this profile is allowed to do on this session.',
      steps: [
        'Connect first — identity is mandatory before any command.',
        'Press Identify ECU to run the family-specific identification exchange (legacy 16M uses its own register, not KWP 1A 80).',
        'Read What this ECU supports: green rows are implemented, grey rows explain what evidence is missing.',
        'Use the Link card to confirm baud rate, init method, addresses and negotiated timings.',
      ],
      tags: ['identity', 'capabilities', 'link', 'overview', 'evidence'],
    },
    {
      id: 'view-equipment', name: 'Equipment guide — interfaces, leads and accessories', category: 'link',
      view: 'equipment',
      summary: 'Which interface matches which protocol, which bike-specific lead you need, and the affiliate-disclosure rules for the Amazon search links.',
      steps: [
        'Find your protocol in Choose the interface for the protocol (KKL/FTDI K-Line, USB CAN SLCAN, SocketCAN, PCAN, ELM327 J1850, Buell TTL).',
        'Select one interface and one bike lead — you do not need every item listed.',
        'Confirm connector, pinout, voltage and baud rate against the manual before ordering.',
      ],
      caution: 'Search links are not inspected products. The hosted browser demo cannot reach hardware at all.',
      tags: ['adapter', 'cable', 'kkl', 'ftdi', 'slcan', 'pcan', 'elm327', 'lead', 'buy'],
    },
    {
      id: 'view-live', name: 'Live data — gauges, timeline, derived channels and findings', category: 'dash',
      view: 'live', selector: '#livePlotPanel',
      summary: 'Poll the ECU, decode every supported channel, plot a multi-scale timeline, compute derived values and run plausibility checks — with the raw bytes kept beside every value.',
      steps: [
        'Press Start polling. The cadence comes from Quick Settings or Preferences (150–2000 ms).',
        'Tick channels in the channel list; the timeline gives each channel its own scale and shows gaps where a reading was missing.',
        'Derived by the workstation is arithmetic, not ECU data — each derived row names its inputs.',
        'Plausibility checks are opinions with their numbers attached; they are a place to start looking, never a diagnosis.',
        'Export Live CSV writes the current session’s samples; Raw provenance holds the bytes behind every decoded value.',
      ],
      tags: ['live', 'gauge', 'poll', 'timeline', 'log', 'derived', 'plausibility', 'csv'],
    },
    {
      id: 'view-sessions', name: 'Sessions — recording, events and replay', category: 'dash',
      view: 'sessions', selector: '#replayPanel',
      summary: 'Every session writes frames, samples, faults and safety decisions to disk; replay recomputes derived values and findings from the recorded bytes.',
      steps: [
        'Recorded sessions lists the JSON logs in ~/.guzzionboard/sessions (the folder is shown above the list).',
        'Select a session to read its event timeline: connections, reads, refusals, acknowledgements and writes.',
        'Replay scrubs through the recording with the derived maths recomputed at each point.',
        'Compare two sessions names the channels that moved between them — means, not time-aligned traces.',
      ],
      tags: ['sessions', 'record', 'replay', 'events', 'compare', 'log'],
    },
    {
      id: 'view-simulator', name: 'Simulated bike — safe practice bench', category: 'dash',
      view: 'simulator',
      summary: 'Drive a simulated engine, seed faults, add latency, drop frames and corrupt checksums to exercise the real retry, timeout and safety paths.',
      steps: [
        'Select the Simulator transport in the Garage, choose the Griso 1200 8V for the fully featured IAW 5AM demo, then connect.',
        'Use Engine controls for throttle, ambient, battery and gear; Start/Stop runs the simulated engine.',
        'Seed a fault and watch the live channels move before the code matures into fault memory.',
        'Add comms latency, dropped frames or checksum corruption to rehearse the failure paths on purpose.',
      ],
      tags: ['simulator', 'sim', 'practice', 'faults', 'latency', 'demo'],
    },
    {
      id: 'view-firmware', name: 'ECU memory — backup, base map, validate, maps, write', category: 'memory',
      view: 'firmware', selector: '#firmwareIntroPanel',
      summary: 'The whole calibration pipeline in one workspace: adapter pre-flight, dual-read backup, mandatory base map vault, image validation, XDF map editing and the gated write.',
      steps: [
        'Start at 1 · Adapter pre-flight, then 2 · Backup.',
        'Confirm the base map was vaulted (2b) — a write is refused without it.',
        'Render the dump in Maps & tables, edit with an XDF, build a tune, then run Validate and the Write gate.',
        'The firmware filter pills at the top of the view narrow the page to Maps, Backup or Write.',
      ],
      tags: ['firmware', 'memory', 'backup', 'basemap', 'validate', 'write', 'rom', 'flash'],
    },
    {
      id: 'view-faults', name: 'Fault codes — stored and current DTCs', category: 'diagnostics',
      view: 'faults', selector: '#faultList',
      summary: 'Read stored and current diagnostic trouble codes, clear them behind an explicit gate, and look codes up in a local Harley reference file.',
      steps: [
        'Press Read DTCs. Counts and the raw payload are shown with each code.',
        'Clear DTCs requires a confirmation and the documented engine state; the clear is recorded in the session log.',
        'Harley trouble-code reference accepts a local JSON file — nothing is uploaded and no fitment is claimed.',
      ],
      tags: ['dtc', 'faults', 'codes', 'harley', 'clear', 'diagnostics'],
    },
    {
      id: 'view-procedures', name: 'Guided tests — bounded, verdict-returning procedures', category: 'diagnostics',
      view: 'procedures', selector: '#procedureList',
      summary: 'A guided test establishes a known state, performs one bounded action, watches the right channels and states what the result means.',
      steps: [
        'Pick a test that the connected profile offers; unavailable tests list the missing capabilities.',
        'Follow the preconditions exactly — engine state matters (off, running or either).',
        'Run the test; observations are ordinary live reads and every actuation appears in the session log.',
        'Read the verdict together with the channels and thresholds it used.',
      ],
      caution: 'Guided tests can energise injectors, coils or the fuel pump. Treat the bike as live.',
      tags: ['procedure', 'guided', 'test', 'verdict', 'diagnostics'],
    },
    {
      id: 'view-service', name: 'Service actions — actuators, routines and resets', category: 'diagnostics',
      view: 'service', selector: '#actuatorList',
      summary: 'Actuator pulses and adaptation resets, each behind a precondition card. IAW ECUs have no output timer, so the workstation owns the deadline and always releases.',
      steps: [
        'Read the precondition card; the action stays disabled until the state matches.',
        'Pulse an actuator for the offered duration. Release is automatic on expiry, on disconnect and if the browser goes away.',
        'Adaptation and learning resets discard learned values and cannot be undone — they are recorded as safety decisions.',
      ],
      caution: 'Injectors squirt fuel, coils make sparks, the pump pressurises the rail. Secure the bike and ventilate the area.',
      tags: ['actuator', 'routine', 'reset', 'adaptation', 'tps', 'service'],
    },
    {
      id: 'view-tools', name: 'Tools — the workshop utilities bench', category: 'workshop',
      view: 'tools', selector: '#toolsOrganizer',
      summary: 'Standalone helpers that need no ECU connection, grouped by manufacturer: General tools that fit any bike, then Bajaj, Buell, CFMoto, Harley-Davidson, Honda and Yamaha, plus aftermarket entries for BRT Juken, Dynojet and rusEFI.',
      steps: [
        'Pick a brand in the Brand dropdown (or press "Only <brand>" on a group heading) to see just that maker\'s modules; General tools work on any motorcycle.',
        'Filter with the category pills (Workshop & Service, Fitment & Reference, Decoders & Telemetry, Maps & Checksums, Live Serial / CAN). Brand and category combine.',
        'Search by bike, ECU family, part number or task in the search box — search covers every brand at once.',
        'Open a module; most are collapsed <details> cards — click the summary row to expand.',
        'Focus mode hides every other module so one tool fills the bench.',
      ],
      tags: ['tools', 'utilities', 'bench', 'workshop', 'research'],
    },
    {
      id: 'view-discovery', name: 'Discovery — identifier sweeps and capture analysis', category: 'diagnostics',
      view: 'discovery', selector: '#scanBtn',
      summary: 'Read-only RLI identifier sweeps, offline CAN identifier-pair analysis, live HD-LAN and Yamaha dashboard-stream observation, and K-Line identifier discovery.',
      steps: [
        'RLI sweep ranges are offered only where the service is established non-mutating; compare key-on/engine-off with an instructed running sweep.',
        'Paste an existing CAN capture into the CAN identifier analyzer to find likely request/response pairs — the workstation never creates traffic for this.',
        'Live observation panels require a SocketCAN interface (or FTDI KKL for Yamaha) and an explicit confirmation.',
      ],
      caution: 'Unknown families are never probed on a customer bike.',
      tags: ['discovery', 'sweep', 'rli', 'can', 'identifier', 'hdslan', 'yamaha', 'kline'],
    },
    {
      id: 'view-report', name: 'Report — shareable session snapshot', category: 'workshop',
      view: 'report', selector: '#buildReportBtn',
      summary: 'Builds a text report of identification, faults, live values and every safety decision, downloadable as .txt or .json.',
      steps: [
        'Connect and gather the data you want (identify, read DTCs, poll live data).',
        'Press Build report, then Download .txt or Download .json.',
        'File → Save Report to Active Save Preset writes it into the configured exports folder.',
      ],
      tags: ['report', 'export', 'pdf', 'print', 'txt', 'json'],
    },
    {
      id: 'view-help', name: 'Help & guides — this knowledge base', category: 'workshop',
      view: 'help',
      summary: 'Every guide, tool manual, protocol reference, ECU catalog entry, checksum explanation and glossary term, with shareable permalinks and global search.',
      steps: [
        'Press Ctrl+K (Cmd+K on macOS) anywhere for the global search spotlight.',
        'Filter with the category pills, or type into the help search box.',
        'Every article has a #help/<topic> permalink; the Copy link button puts it on the clipboard.',
        'Jump buttons in each article take you straight to the live panel it describes.',
      ],
      tags: ['help', 'docs', 'guides', 'search', 'reference', 'manual'],
    },

    /* ------------------------------------------------ global chrome */
    {
      id: 'global-search', name: 'Global program search (Ctrl+K spotlight)', category: 'search',
      selector: '#helpSpotlightInput',
      summary: 'One search box over every guide, workspace view, panel, menu command, ECU family, XDF file and glossary term — with keyboard navigation.',
      steps: [
        'Press Ctrl+K (Cmd+K) or click Search & Help in the menu bar.',
        'Type a bike, ECU, part number, protocol, checksum, tool name or task ("backup", "afr", "5am", "harley").',
        'Use ↑ / ↓ to move and Enter to open; Esc closes.',
        'Scope pills narrow results to Guides, Tools, or ECUs & XDFs.',
      ],
      tags: ['search', 'ctrl+k', 'spotlight', 'find', 'command'],
    },
    {
      id: 'preferences-dialog', name: 'Preferences dialog (Ctrl+,)', category: 'search',
      selector: '#openPreferencesBtn',
      summary: 'Theme, density, temperature units, polling cadence, default connection mode, save/load location presets, plus JSON export/import and factory reset.',
      steps: [
        'Open File → Preferences… or press Ctrl+, (Quick Settings also links here).',
        'Changes to theme, density and units preview live; Save Preferences persists them to the backend.',
        'Use Export Preferences (.json) to keep a copy, Import to restore, Reset to Defaults to start over.',
      ],
      tags: ['preferences', 'settings', 'theme', 'units', 'presets', 'export'],
    },
    {
      id: 'preset-browser', name: 'Preset folder browser', category: 'search',
      selector: '#presetBrowserModal',
      summary: 'Browse a configured save or load location preset and pick a file without typing a path.',
      steps: [
        'Open File → Browse Load Preset Folder… or the Browse button next to a path field.',
        'Pick the preset, refresh the listing and choose a file — the path is inserted into the field that asked for it.',
        'Manage Presets… jumps to the preset editor in Preferences.',
      ],
      tags: ['preset', 'folder', 'browse', 'path', 'files'],
    },
    {
      id: 'menu-bar', name: 'Menu bar & command ribbon', category: 'search',
      view: 'garage', selector: '#appMenubar',
      summary: 'File, View, Tuning, Tools, Quick Settings and Help menus, plus the five perspective tabs, live telemetry strip and poll control.',
      steps: [
        'File handles projects, CSV logs, manuals, reports, exports and exit.',
        'View switches workspaces and toggles the explorer dock (Ctrl+B) and compact notes.',
        'Tuning jumps straight into the XDF editor, base map, builder, AFR overlay, backup, compare and write gates.',
        'Tools opens diagnostics, procedures, discovery and the utilities bench.',
        'Quick Settings changes theme, density, units, poll cadence and active presets.',
      ],
      tags: ['menu', 'ribbon', 'perspectives', 'file', 'view', 'tuning', 'tools', 'quick settings'],
    },

    /* ------------------------------------------------ diagnostics panels */
    {
      id: 'protocol-panel', name: 'Protocol evidence & updates', category: 'diagnostics',
      view: 'garage', selector: '#protocolPanel',
      summary: 'Shows the evidence behind the selected ECU’s protocol and lets a qualified hardware confirmation build a read-level update from a signed pack.',
      steps: [
        'Read the evidence rows before trusting a capability.',
        'The desktop checks for published signed packs at startup and periodically.',
        'Applied packs are recorded with key id, catalog revision and revert history; reverting restores the previous definition.',
      ],
      caution: 'An update can only add read-level behaviour supported by a qualifying confirmation — it cannot invent a write path.',
      tags: ['protocol', 'evidence', 'updates', 'signed', 'trusted', 'keys'],
    },
    {
      id: 'identity-panel', name: 'ECU identification', category: 'link',
      view: 'overview', selector: '#identityPanel',
      summary: 'Mandatory identification exchange before any command, using the family-specific method (legacy 16M does not use KWP 1A 80).',
      steps: [
        'Connect, then press Identify ECU.',
        'The report lists part numbers, hardware/software IDs and the raw response.',
        'Identification is the fitment evidence used by later gates (hardware family, base map, write).',
      ],
      tags: ['identify', 'identity', 'part number', 'hardware', 'software'],
    },
    {
      id: 'harley-code-reference', name: 'Harley trouble-code reference', category: 'diagnostics',
      view: 'faults', selector: '#harleyCodeReference',
      summary: 'Look up Harley-Davidson trouble codes from a local JSON file; descriptions only, no fitment or protocol claims.',
      steps: [
        'Load a local Harley trouble-codes JSON file.',
        'Type a code (duplicates and nonstandard strings are preserved).',
        'Nothing is uploaded and no diagnostic protocol is implied.',
      ],
      tags: ['harley', 'trouble codes', 'dtc', 'reference', 'json'],
    },

    /* ------------------------------------------------ ECU memory panels */
    {
      id: 'adapter-panel', name: '1 · Adapter pre-flight (latency timer check)', category: 'memory',
      view: 'firmware', selector: '#adapterPanel',
      summary: 'Checks the serial adapter, measures round-trip latency and explains the FTDI latency timer that turns a 20-minute read into hours.',
      steps: [
        'Enter the adapter port and press Check adapter.',
        'Use Measure latency to see round-trip time; GuzziDiag calls a 1 ms latency timer essential (16 ms is the usual culprit).',
        'On Windows with no COM port, the check points at the mirrored WHQL CDM driver bundle.',
        'J2534 devices can be enumerated where a vendor DLL is installed.',
      ],
      tags: ['adapter', 'latency', 'ftdi', 'driver', 'j2534', 'preflight'],
    },
    {
      id: 'backup-panel', name: '2 · Backup (dual-read memory dump)', category: 'memory',
      view: 'firmware', selector: '#backupPanel',
      summary: 'Reads the ECU memory twice and keeps the file only if both reads agree byte for byte; a verified backup also vaults the base map.',
      steps: [
        'Choose the region (flash or EEPROM) where the profile implements it.',
        'Press Backup. Two complete reads are compared; any disagreement aborts and keeps nothing.',
        'Watch the progress bar and the per-block result — 5AM reads 19 blocks and reports skipped blocks explicitly.',
        'A verified image is hashed, described, saved and vaulted as the base map.',
      ],
      caution: 'One read over a noisy K-Line is not a backup. Never write from a single read.',
      tags: ['backup', 'read', 'dump', 'memory', 'verified', '5am', 'blocks'],
    },
    {
      id: 'memory-compare-panel', name: 'Compare two ECU image files', category: 'memory',
      view: 'firmware', selector: '#memoryComparePanel',
      summary: 'Byte-level comparison of any two local images, with ranges, counts and a copyable difference summary.',
      steps: [
        'Choose the first and second image file.',
        'Compare to list differing ranges and totals.',
        'Identical bytes show repeatability only — not completeness, layout correctness or restorability.',
      ],
      tags: ['compare', 'diff', 'image', 'binary', 'verify'],
    },
    {
      id: 'base-map-panel', name: '2b · Base map vault (mandatory before write)', category: 'memory',
      view: 'firmware', selector: '#baseMapPanel',
      summary: 'The untouched calibration the bike arrived with, stored with its SHA-256 and re-hashed before every write.',
      steps: [
        'A verified backup files a base map automatically.',
        'You can save another image as the base map, or restore/export the vaulted one.',
        'Attest external verified full backup accepts a 304 KiB flash image or a 320 KiB GuzziDiag/IAW5xReader full dump (the 0x4000 bootloader prefix is sliced off).',
      ],
      caution: 'The attestation checkbox is a statement of fact: the file must be a verified full backup from this exact ECU.',
      tags: ['base map', 'vault', 'attest', 'backup', 'sha256', 'guzzidiag', '5am'],
    },
    {
      id: 'validate-panel', name: '3 · Validate an image', category: 'memory',
      view: 'firmware', selector: '#validatePanel',
      summary: 'Checks size, vector table, entropy and hardware family before a single byte is sent — an HW1xx image never goes into an HW3xx ECU.',
      steps: [
        'Choose the image file and press Validate.',
        'Read the hardware-family detection and every failed check.',
        'A validation failure blocks the write gate; there is no override for a hardware-family mismatch.',
      ],
      tags: ['validate', 'hardware family', 'size', 'entropy', 'vector', 'image'],
    },
    {
      id: 'maps-panel', name: 'Maps & tables — XDF calibration editor', category: 'calibration',
      view: 'firmware', selector: '#mapsCard',
      summary: 'Render a dump as named tables with a TunerPro XDF definition, edit cells and constants, toggle flags, apply binary patches and review a diff before building.',
      steps: [
        'Choose the image and an XDF (bundled library or your own file in ~/.guzzionboard/xdfs).',
        'Render to build the table tree; the explorer dock lists every table, constant, flag and patch.',
        'Edit cells (click, type, Enter). The change table records expected raw values and reversions.',
        'Use Flags & Switches and Binary patches sections for bit flags and hex patches; mismatched base data must be confirmed explicitly.',
        'Review the diff, then preview and build the tune.',
      ],
      tags: ['xdf', 'maps', 'tables', 'editor', 'constants', 'flags', 'patches', 'render', 'diff'],
    },
    {
      id: 'write-panel', name: '4 · Write — the gated flash', category: 'memory',
      view: 'firmware', selector: '#writePanel',
      summary: 'Writing stays refused until every precondition is green: base map hash, hardware family, checksum provider, confirmation token, backup verification and writer unlock.',
      steps: [
        'Validate the built image first, then open 4 · Write.',
        'Work through the precondition list; each row names exactly what it needs.',
        'Enable programming for this session, then unlock implemented hardware writers with the recovery acknowledgement.',
        'Build the confirmation token and verify it — tokens are single use.',
        'Press Write last; the write is streamed, read back and verified where the protocol implements verification.',
      ],
      caution: 'A failed write can brick an ECU. Have a bench recovery plan and a verified backup before you start.',
      tags: ['write', 'flash', 'programming', 'gate', 'token', 'unlock', 'preconditions', 'brick'],
    },
    {
      id: 'security-panel', name: 'SecurityAccess key providers', category: 'memory',
      view: 'firmware', selector: '#securityPanel',
      summary: 'Seed/key algorithms for SecurityAccess. No verified Guzzi algorithm ships with the project; you supply a trusted plugin.',
      steps: [
        'Install a key provider plugin in ~/.guzzionboard/security (see Preferences → paths).',
        'Select the provider and let the workstation request the seed and compute the key.',
        'An unverified provider can be armed for a session behind an explicit acknowledgement; the session log records it.',
      ],
      caution: 'A wrong key count can lock the ECU for a period. Use only algorithms you trust.',
      tags: ['security', 'seed', 'key', 'securityaccess', 'plugin'],
    },

    /* ------------------------------------------------ tools bench */
    {
      id: 'ecu-lookup', name: 'ECU number & bike research', category: 'reference',
      view: 'tools', selector: '#ecuLookup',
      summary: 'Look up ECU part, hardware and software identifiers from the label or identification report against the local catalog and an optional reference list.',
      steps: [
        'Type the part/hardware/software identifiers from the ECU label — never a VIN.',
        'Matches are leads: they do not prove fitment, software compatibility, checksum or flashing support.',
        'Load a local reference list to extend the search; nothing is uploaded.',
      ],
      tags: ['ecu lookup', 'part number', 'hardware', 'software', 'label', 'reference'],
    },
    {
      id: 'shared-ecu-research', name: 'Shared ECU family cross-reference', category: 'reference',
      view: 'tools', selector: '#sharedEcuResearch',
      summary: 'Motorcycles across makes that map to the same catalog ECU profile, plus XDFs labelled for the related family.',
      steps: [
        'Load the cross-reference, then choose an ECU family.',
        'Review the makes/models/years and the related XDF files.',
        'Entries and years are source-based leads, not proof of identical part number or software.',
      ],
      tags: ['cross-reference', 'shared', 'family', 'xdf', 'fitment'],
    },
    {
      id: 'honda-vfr-checksum', name: 'Honda source-ID · calibration checksum', category: 'calibration', brand: 'honda',
      view: 'tools', selector: '#hondaVfrChecksum',
      summary: '44 source-scoped Honda ECM candidates: compares an original and an edited image of the stated length, validates the candidate ID and zero-byte sum, and proposes the checksum-byte correction.',
      steps: [
        'Choose the source variant and the original and edited image files.',
        'Tick the confirmation and press Inspect.',
        'Review the proposed checksum byte, then Export to write a corrected copy.',
      ],
      caution: 'Source-scoped only; it does not apply to other Honda calibrations or other brands.',
      tags: ['honda', 'checksum', 'calibration', 'zero byte sum', 'repair'],
    },
    {
      id: 'honda-offline', name: 'Honda K-Line · offline response decoder', category: 'telemetry', brand: 'honda',
      view: 'tools', selector: '#hondaOffline',
      summary: 'Decode complete Honda K-Line response frames pasted one hex frame per line, using a third-party implementation tested on a 2005 CBR600RR.',
      steps: [
        'Paste complete frames (one per line) into the box.',
        'Press Decode; a checksum mismatch refuses decoding.',
        'Results are research candidates — not vehicle identification and not hardware-validated by this project.',
      ],
      tags: ['honda', 'kline', 'offline', 'decode', 'frames', 'checksum'],
    },
    {
      id: 'multi-research', name: 'Multi-brand offline capture research', category: 'telemetry',
      view: 'tools', selector: '#multiResearch',
      summary: 'Choose a research profile (BMW, Ducati, Yamaha and others) and paste previously captured frames to see candidate interpretations.',
      steps: [
        'Select the exact research profile.',
        'Paste complete frames, one per line.',
        'Read candidate values with their confidence; nothing here is a confirmed reading.',
      ],
      tags: ['multi-brand', 'capture', 'research', 'bmw', 'ducati', 'decode'],
    },
    {
      id: 'etv-research', name: 'Ride-by-wire torque inversion (OpenETV research)', category: 'calibration',
      view: 'tools', selector: '#etvResearch',
      summary: 'Estimates throttle opening from user-supplied engine-torque and rider-request tables (CSV rows RPM, columns throttle %, cells Nm).',
      steps: [
        'Paste or load the engine torque table and the rider request table.',
        'Press Invert to compute the estimated throttle opening per operating point.',
        'Synthetic-tested only — treat output as a research estimate.',
      ],
      tags: ['etv', 'ride-by-wire', 'torque', 'openetv', 'throttle', 'research'],
    },
    {
      id: 'tuning-research', name: 'Multi-brand tuning research links', category: 'reference',
      view: 'tools', selector: '#tuningResearch',
      summary: 'Source links for brands with no bundled definition: research pointers only, with no maps, firmware, write commands or checksum repair.',
      steps: [
        'Pick a brand/family.',
        'Read the source notes and what remains unverified.',
        'Nothing in this panel can write to an ECU.',
      ],
      tags: ['tuning research', 'links', 'brands', 'sources'],
    },
    {
      id: 'juken-research', name: 'BRT Juken 5 · offline map-block research', category: 'calibration', brand: 'britek',
      view: 'tools', selector: '#jukenResearch',
      summary: 'Inspect a user-supplied 10,248-byte raw core block using an independently published layout.',
      steps: [
        'Choose the raw core block file.',
        'Inspect the decoded map blocks and offsets.',
        'The source has not tested bulk decoding on hardware; a matching file size proves nothing.',
      ],
      tags: ['juken', 'brt', 'map block', 'research', 'offsets'],
    },
    {
      id: 'harley-region', name: 'Harley Delphi · offline calibration region workspace', category: 'calibration', brand: 'harley',
      view: 'tools', selector: '#harleyRegion',
      summary: 'Inspect a local 160 KiB calibration or 16 KiB tune, compare two regions, or export the 16 KiB region as a new research file (HarleyECUTool layout, ~2014–2020).',
      steps: [
        'Choose a calibration or tune file.',
        'Inspect the region map, or compare a calibration against a tune.',
        'Export the 16 KiB region as a separate research file.',
      ],
      caution: 'Does not identify the motorcycle, verify a checksum, or write to a Delphi ECU by itself.',
      tags: ['harley', 'delphi', 'calibration', 'region', 'tune', '160k', '16k'],
    },
    {
      id: 'centurion-research', name: 'Harley Centurion · local header research', category: 'calibration', brand: 'harley',
      view: 'tools', selector: '#centurionResearch',
      summary: 'Inspect candidate ECU-part and calibration fields of up to two user-supplied Delphi-like Centurion files.',
      steps: [
        'Choose up to two files.',
        'Compare the candidate header fields side by side.',
        'Unknown headers stay unknown — no fitment or checksum claim is made.',
      ],
      tags: ['harley', 'centurion', 'header', 'research', 'compare'],
    },
    {
      id: 'pvv-editor', name: 'Power Vision PVV · local table editor', category: 'calibration', brand: 'harley',
      view: 'tools', selector: '#pvvEditor',
      summary: 'Open a user-supplied PVV XML, inspect its tables and make explicit numeric cell edits into a separate XML copy.',
      steps: [
        'Choose a PVV XML file to inspect its tables.',
        'Edit cells and review the staged change list.',
        'Save As writes a new XML copy; the original is untouched.',
      ],
      caution: 'No Power Vision device connection and no vehicle/checksum verification.',
      tags: ['power vision', 'pvv', 'harley', 'xml', 'tables', 'editor'],
    },
    {
      id: 'jetdrive-panel', name: 'Dynojet JetDrive · live network observation', category: 'telemetry', brand: 'dynojet',
      view: 'tools', selector: '#jetdrivePanel',
      summary: 'Observe a three-second window of JetDrive-compatible multicast on the local dyno network and hand the capture to the AFR overlay.',
      steps: [
        'Confirm you are on the dyno network and press Capture.',
        'Review the per-channel sample counts and ranges.',
        'Press Send capture to Map AFR Overlay to pivot the samples into aligned wide frames for the offline analyzer.',
      ],
      caution: 'Dyno telemetry, not an ECU connection or tune writer. Integration is synthetic-tested only.',
      tags: ['jetdrive', 'dynojet', 'dyno', 'multicast', 'afr', 'overlay'],
    },
    {
      id: 'harley-memory', name: 'Harley Delphi CAN · experimental live memory', category: 'hardware', brand: 'harley',
      view: 'tools', selector: '#harleyMemory',
      summary: 'Source-scoped candidate Delphi CAN memory read and 16 KiB tune write on a SocketCAN channel.',
      steps: [
        'Configure the CAN channel and a capture path.',
        'Tick the confirmation and press Read to capture the current calibration.',
        'Review the experimental write panel before attempting any write.',
      ],
      caution: 'A read first downloads an authentication payload to ECU address zero, which can alter ECU state. Synthetic-tested only.',
      tags: ['harley', 'delphi', 'can', 'memory', 'read', 'write', 'experimental'],
    },
    {
      id: 'buell-ddfi', name: 'Buell DDFI · live serial research', category: 'hardware', brand: 'buell',
      view: 'tools', selector: '#buellDdfi',
      summary: 'Live serial read and experimental fuel/spark EEPROM write for compatible Buell DDFI/DDFI-2/DDFI-3 ECMs over a TTL serial adapter.',
      steps: [
        'Enter the TTL serial port and confirm the wiring/voltage.',
        'Identify the ECM to confirm the DDFI generation.',
        'Read live data; the experimental write panel stays locked until its own preconditions are met.',
      ],
      caution: '5 V TTL maximum. Not ELM327/J1850, OBD or RS-232.',
      tags: ['buell', 'ddfi', 'ttl', 'serial', 'eeprom', 'harley'],
    },
    {
      id: 'rusefi-research', name: 'rusEFI aftermarket · live serial research', category: 'hardware', brand: 'rusefi',
      view: 'tools', selector: '#rusefiResearch',
      summary: 'Live serial research for an explicitly selected aftermarket rusEFI controller (including one running a Harley engine).',
      steps: [
        'Select the serial port and the rusEFI profile.',
        'Read live data and the calibration page list.',
        'The tune read/write panel is separate and gated by its own confirmation.',
      ],
      caution: 'Not for stock Delphi ECUs or a Power Vision tuner. Synthetic-tested only.',
      tags: ['rusefi', 'aftermarket', 'serial', 'live', 'tune', 'ini'],
    },
    {
      id: 'yamaha-research', name: 'Yamaha MT image checksum · offline research', category: 'calibration', brand: 'yamaha',
      view: 'tools', selector: '#yamahaResearch',
      summary: 'Inspect a plain binary against one third-party Yamaha MT word-sum layout; inspection never edits or uploads the file.',
      steps: [
        'Choose the image file.',
        'Inspect the computed and stored checksum words.',
        'Mismatch means the layout may not apply — it is research, not a repair.',
      ],
      tags: ['yamaha', 'checksum', 'image', 'research', 'word sum'],
    },
    {
      id: 'bajaj-checksum', name: 'Bajaj RS200 · Dell’Orto checksum research', category: 'calibration', brand: 'bajaj',
      view: 'tools', selector: '#bajajChecksum',
      summary: 'Inspect a 768 KiB raw image for the source-reported 2024 RS200 JL351458010651 family and export a copy with one 16-bit checksum updated.',
      steps: [
        'Choose the raw image and inspect the checksum location.',
        'Tick the confirmation to allow the export.',
        'Export writes a new file; the original is never modified.',
      ],
      tags: ['bajaj', 'rs200', 'checksum', 'dellorto', 'export'],
    },
    {
      id: 'cfmoto-checksum', name: 'CFMoto Bosch MSE6 · offline research', category: 'calibration', brand: 'cfmoto',
      view: 'tools', selector: '#cfmotoChecksum',
      summary: 'Inspect a local binary with the source’s MSE6 record heuristic (2024 NK250 / 2023 450SR); inspection only, no file produced.',
      steps: [
        'Choose the image file and inspect.',
        'Read the record heuristic results and reported mismatches.',
        'It does not identify an ECU and never writes a file.',
      ],
      tags: ['cfmoto', 'bosch', 'mse6', 'checksum', 'research'],
    },
    {
      id: 'service-interval', name: 'Service interval worksheet', category: 'workshop',
      view: 'tools', selector: '#workshopService',
      summary: 'Arithmetic on last documented service, current odometer and interval — it never infers that a service happened.',
      steps: [
        'Enter last service km, current km and the interval from the manual.',
        'Press the due check to see remaining distance or overdue amount.',
        'Verify intervals, initial services and severe-use rules in the manual.',
      ],
      tags: ['service', 'interval', 'odometer', 'workshop', 'maintenance'],
    },
    {
      id: 'manual-search', name: 'Search a local manual text', category: 'workshop',
      view: 'tools', selector: '#workshopManual',
      summary: 'Exact-text search of a user-supplied UTF-8 .txt manual export for part numbers or torque terms, entirely in memory.',
      steps: [
        'Load the .txt export and type the exact term.',
        'Review matching lines with context.',
        'The file stays in the tab; PDF, OCR, semantic search and AI answers are not offered.',
      ],
      tags: ['manual', 'search', 'text', 'torque', 'workshop'],
    },
    {
      id: 'shim-worksheet', name: 'Manual shim worksheet', category: 'workshop',
      view: 'tools', selector: '#shimWorksheetPanel',
      summary: 'Arithmetic only: given measured clearance, current shim, target range and direction, it lists candidate shim sizes.',
      steps: [
        'Enter measured clearance, current shim thickness, target min/max and the direction.',
        'Confirm the direction checkbox — it is required.',
        'Read the candidate shims; no engine specification is assumed.',
      ],
      tags: ['shim', 'valve', 'clearance', 'workshop', 'calculator'],
    },
    {
      id: 'gearing-calculator', name: 'Gearing & road speed', category: 'workshop',
      view: 'tools', selector: '#gearingPanel',
      summary: 'Road speed per gear at a chosen engine speed from gearbox ratios and final drive, with presets and full manual entry.',
      steps: [
        'Pick a bike preset or enter ratios, primary drive, final drive and tyre circumference.',
        'Enter engine speed and read the speed table per gear.',
        'Change sprockets to compare setups before buying parts.',
      ],
      tags: ['gearing', 'speed', 'sprocket', 'ratios', 'calculator'],
    },
    {
      id: 'z2-converter', name: 'Wideband log converter (Zeitronix ZT-2 → LogWorks)', category: 'workshop',
      view: 'tools', selector: '#z2ConverterPanel',
      summary: 'Converts a Zeitronix ZDL CSV (AFR, RPM, TPS, MAP, EGT…) into a LogWorks/Excel DIF table, with the documented timeline offset fixed.',
      steps: [
        'Load the ZDL CSV export.',
        'Choose channels and the timeline offset handling.',
        'Download the DIF and open it in LogWorks or Excel.',
      ],
      tags: ['zeitronix', 'wideband', 'afr', 'csv', 'dif', 'logworks'],
    },
    {
      id: 'rpm-signal', name: 'Bench RPM trigger signal', category: 'workshop',
      view: 'tools', selector: '#rpmSignalPanel',
      summary: 'Renders a crank/cam trigger-wheel pattern to a WAV file so a bench ECU believes the engine is turning.',
      steps: [
        'Choose the trigger pattern, tooth count and target RPM.',
        'Render the WAV and check the timing summary.',
        'Play it through an AC-coupled buffer into the sensor input; never connect it to a running engine.',
      ],
      tags: ['rpm', 'trigger', 'wav', 'bench', 'crank', 'signal'],
    },
    {
      id: 'checksum-workbench', name: 'Checksum workbench & algorithm finder', category: 'calibration',
      view: 'tools', selector: '#checksumWorkbench',
      summary: 'Sweeps the common whole-file checksums (byte and word sums, XOR, CRC-16, CRC-32) over the usual stored positions, names every combination that agrees with the image, and repairs a copy.',
      steps: [
        'Choose the local binary image. The original file is read, never written.',
        'Leave the checksum position empty to sweep the head and tail, or type the exact offset you were told the word lives at.',
        'Set Data starts at when the image carries a header the checksum skips.',
        'Read the ranked rows: algorithm, stored offset, width, byte order, stored and computed value. A "one\u2019s complement" row means the file stores the inverse of the computed word.',
        'Press Repair a copy on the row that matches, then download the repaired file and compare the two SHA-256 hashes shown.',
      ],
      caution: 'A matching checksum is arithmetic on your file. It does not prove the image is complete, that it belongs to a particular ECU, or that it is safe to flash. The write gate still applies.',
      tags: ['checksum', 'crc32', 'crc16', 'sum', 'xor', 'repair', 'binary', 'verify'],
    },
    {
      id: 'rom-region-map', name: 'ROM region & entropy map', category: 'calibration',
      view: 'tools', selector: '#romMapPanel',
      summary: 'Draws a sliding-window entropy strip over an unknown dump, merges it into regions (padding, code, table-like data, sparse) and diffs two images byte by byte.',
      steps: [
        'Load the image whose shape you want to see, and optionally a second image to compare.',
        'Choose the window size: 128–256 bytes shows structure, 1 KiB smooths it into blocks.',
        'Read the strip: flat runs are padding, tall runs are code or compressed data, mid-height plateaus are usually tables.',
        'Use the region table for offsets and dominant bytes, then author or load an XDF for that address range.',
        'Load a second image to see exactly which regions differ — the checksum word and header will appear there too.',
      ],
      caution: 'Entropy says what kind of data a region holds, never which table it is. Matching an address to a table name is still the XDF\u2019s claim, not proof.',
      tags: ['entropy', 'rom', 'region', 'binwalk', 'diff', 'padding', 'tables', 'dump'],
    },
    {
      id: 'xdf-library-finder', name: 'XDF library table finder', category: 'reference',
      view: 'tools', selector: '#xdfFinderPanel',
      summary: 'Searches all 121 bundled calibration definitions at once by table name, units, category, address or definition label, and narrows by brand.',
      steps: [
        'Type a term — injection, idle, rev limit — and press Enter or Search.',
        'Restrict the brand to see one manufacturer\u2019s definitions only.',
        'Switch Field to Address to search 0xB024, B024 or a decimal offset.',
        'Each group names the definition, its bike and its filename; Copy puts filename · table @ address on the clipboard and opens the ECU memory view.',
      ],
      caution: 'The index is a table of contents: it lists what each definition claims, not what your dump contains. Two definitions can put different tables at the same address.',
      tags: ['xdf', 'library', 'table', 'search', 'address', 'units', 'definition', 'brand'],
    },
    {
      id: 'wideband-transfer', name: 'Wideband transfer-function lab', category: 'telemetry',
      view: 'tools', selector: '#widebandLab',
      summary: 'Converts logged wideband voltage to AFR and lambda with the controller\u2019s published curve (Innovate LC-2, Zeitronix ZT-2, AEM X-series or custom) and converts between fuel stoichiometries.',
      steps: [
        'Pick the controller that produced the log. Tick First column is time when the export leads with timestamps.',
        'Pick the fuel so lambda is computed against the right stoichiometric ratio.',
        'Paste the voltage column and press Convert; read AFR, lambda and a status per sample.',
        'Use the two-point check to see what a measured-versus-reference correction would scale the log by.',
      ],
      caution: 'A controller is only as accurate as the curve it was programmed with. Verify the analog output settings in the controller before trusting a converted log; an AEM unit below 0.5 V is reporting "sensor not ready", not a lean mixture.',
      tags: ['wideband', 'afr', 'lambda', 'innovate', 'zeitronix', 'aem', 'stoich', 'e85', 'transfer function'],
    },
    {
      id: 'frame-lab', name: 'J1939 & ISO-TP frame lab', category: 'telemetry',
      view: 'tools', selector: '#frameLabPanel',
      summary: 'Decodes extended CAN identifiers as J1939 (priority, PGN, source address), segments and reassembles ISO-TP payloads, and composes or validates KWP2000 requests.',
      steps: [
        'Paste candump lines in either form — can0 18FEF100 [8] 01 02 … or can0 18FEF100#0102 … — and press Decode.',
        'Read the census: identifier, frame count, length, sample bytes, then PGN, PGN name, source address and whether the PGN is PDU1 or PDU2.',
        'Use ISO-TP segments to cut a payload into single/first/consecutive frames, or Join to assemble frames you paste back.',
        'Use the KWP2000 composer to see the format byte, addressing and low-byte sum the diagnostics view would send.',
      ],
      caution: 'Frames composed here are text. Nothing in this panel opens a port, and a decoded PGN does not prove which ECU produced it.',
      tags: ['j1939', 'pgn', 'iso-tp', 'iso 15765', 'can', 'kwp2000', 'frame', 'candump', 'segment'],
    },
    {
      id: 'mlg-log-importer', name: 'MLVLG log importer (TunerStudio / MegaLogViewer)', category: 'telemetry',
      view: 'tools', selector: '#mlgLogPanel',
      summary: 'Reads the binary .mlg logs TunerStudio, MegaLogViewer and Speeduino write, shows every channel with its units and scaling, and exports CSV.',
      steps: [
        'Choose the .mlg file. MLVLG version 1 and 2 are supported; anything else is refused by its magic, not guessed at.',
        'Set a record cap if the log is long — parsing stops at that many records rather than freezing the tab.',
        'Read the channel table: name, units, raw type, scale, transform, digits, and the minimum and maximum actually present.',
        'Press Download CSV for a file with one column per channel, already scaled into engineering units.',
      ],
      caution: 'The per-record stamp is a 16-bit counter that wraps and MLVLG does not record its unit, so no seconds are invented. The importer reads a log; it does not verify that the logging device wrote it correctly.',
      tags: ['mlg', 'mlvlg', 'tunerstudio', 'megalogviewer', 'speeduino', 'log', 'csv', 'import'],
    },
    {
      id: 'dbc-frame-decoder', name: 'CAN database (DBC) & frame decoder', category: 'telemetry',
      view: 'tools', selector: '#dbcPanel',
      summary: 'Parses a Vector .dbc — messages, signals, byte order, scaling, units, value tables — and decodes a pasted capture into engineering units.',
      steps: [
        'Load or paste the .dbc, then Parse the database. Messages with their DLC, sender, cycle time and signal count are listed below.',
        'Check the signal table for start bit, length, Intel/Motorola order, sign, factor, offset and unit. A wrong byte order is the usual reason decoded numbers look plausible but wrong.',
        'Paste candump lines and press Decode frames. Rows carry the identifier, message name and each decoded signal.',
        'Download CSV to keep the decoded table beside the raw capture.',
      ],
      caution: 'A DBC is one source\u2019s description of a bus, not an identification: identifiers can collide across model years and a decoded name proves nothing about the motorcycle. Multiplexed signals are skipped rather than guessed.',
      tags: ['dbc', 'can', 'signal', 'decode', 'motorola', 'intel', 'factor', 'value table', 'candump'],
    },
    {
      id: 'obd-explorer', name: 'OBD-II / EOBD explorer', category: 'telemetry',
      view: 'tools', selector: '#obdExplorerPanel',
      summary: 'Decodes Mode 01 live PIDs, Mode 03/07 stored and pending trouble codes and Mode 09 VIN from an ELM327 transcript or a candump capture of the 0x7E8 answer.',
      steps: [
        'Pick a profile: generic SAE J1979, or the Royal Enfield 650 reading list recorded from one owner\u2019s bike.',
        'Paste the transcript — with or without \u201c>\u201d prompts, \u201c0:\u201d frame numbers or a 7E8 header — or the candump lines.',
        'Press Decode: readings show PID, channel, value, the raw bytes behind it and which frame it came from.',
        'Trouble codes and the VIN are decoded separately; a refusal (7F) is reported as a refusal.',
        'Use the gear estimate only with the real gearbox ratios, primary and final drive from the manual.',
      ],
      caution: 'An answer to a PID proves that PID exists on that ECU, not that the value is calibrated, and not which model the bike is. The Royal Enfield entry is one bike\u2019s reading list, not a fitment claim.',
      tags: ['obd', 'obd-ii', 'eobd', 'j1979', 'elm327', 'pid', 'dtc', 'vin', 'royal enfield', 'gear'],
    },
    {
      id: 'tune-file-diff', name: 'Tune-file diff', category: 'calibration',
      view: 'tools', selector: '#tuneDiffPanel',
      summary: 'Compares two calibration files: constants by name, tables cell by cell with row and column, or two logger CSVs column by column.',
      steps: [
        'Choose the first and second file. .msq (XML), TunerStudio-style .ini and CSV exports are recognised by content, not by extension.',
        'Press Compare. Constants list before, after, absolute and percentage change, largest first.',
        'Tables list the number of changed cells, the largest and mean change, whether an axis moved, and the first few changed cells by row and column.',
        'For two CSV logs the table becomes per-column statistics with sample rows.',
      ],
      caution: 'A difference is a question, not an instruction: the same change can be a fix, a mistake, or a different firmware\u2019s addressing. This tool never writes, applies or uploads a tune.',
      tags: ['tune', 'diff', 'compare', 'msq', 'ini', 'mtl', 'motolink', 'xml', 'csv', 'constant', 'table', 'calibration'],
    },

    /* ------------------------------------------- brand frame decoders */
    {
      id: 'kawasaki-kds-decoder', name: 'Kawasaki KDS · K-Line capture decoder', category: 'diagnostics', brand: 'kawasaki',
      view: 'tools', selector: '#kawasakiKds',
      summary: 'Turns a complete Kawasaki KDS K-Line answer into the channel its local identifier carries: throttle, coolant, intake air, engine speed, battery, road speed and the unverified gear byte.',
      steps: [
        'Capture the answer while connected, or paste one from an earlier session. The panel decodes; it never transmits.',
        'Paste the whole addressed response — 80 F1 11 <len> 61 <local id> <data> <checksum>. A frame whose length byte and checksum disagree is rejected before anything is interpreted.',
        'Read the channel beside the raw bytes. The identifier list under the panel shows every local ID this profile implements and the formula behind it.',
        'Where a channel is marked unverified — the gear byte, engine hours — the value is shown raw. Do not turn it into a gear number by eye.',
      ],
      caution: 'Kawasaki defines its own local identifiers; they are not SAE PIDs, and the scalings come from one reverse-engineered source (iKawa) reading one 2006 ER-6n. A value from this panel is a lead for the model in the source, not a fitment claim for another Kawasaki.',
      tags: ['kawasaki', 'kds', 'k-line', 'er-6n', 'er6', 'kwp', 'local identifier', 'throttle', 'coolant'],
    },
    {
      id: 'ktm-kmsk16-decoder', name: 'KTM · Keihin KMSK16 K-Line capture decoder', category: 'diagnostics', brand: 'ktm',
      view: 'tools', selector: '#ktmKmsk16',
      summary: 'Decodes a KWP2000 K-Line capture from a Keihin KMSK16 ECU and names the data identifier: engine speed, coolant, intake air, manifold pressure, throttle angles, injector on-time, ignition timing and dwell, lambda adaption, A/D voltages, switch states and the over-rev counters.',
      steps: [
        'Paste one captured frame per line — 85 F1 12 62 01 00 0B B8 AE is a $22 answer carrying engine speed. The panel checks the format byte, the length and the 8-bit sum before it reads anything.',
        'Read the identifier line first. It names the channel, the source job and Keihin\'s own symbol (NE for engine speed, TW for coolant, PM1 for manifold pressure), so the value can be checked against a service manual instead of trusted.',
        'Watch the word after Value. "stated" means the source gave the scale; "inferred" means it was worked out from the declared range or an example capture, and the line after it says which. A raw byte with no scale is shown as a raw byte.',
        'For the second throttle, paste $22 0170, $22 0172 and $22 0173 together. The panel then computes the percentage across the three frames and labels it as rewritten, because the source\'s own expression divides by a ratio instead of by a span.',
        'A refusal is information: 7F 22 31 means the ECU rejected the read as out of range, and the panel prints the negative-response code in words.',
      ],
      caution: 'Two identifiers in the source disagree with themselves: the over-rev counters carry one range in the job entry and another in the identifier summary, and the battery channel declares 0–5 V beside an example of 11.7 V. The panel shows both readings and derives no number from either. Reading live data may need security access on some paths, and this project neither ships the key nor transmits anything.',
      tags: ['ktm', 'kmsk16', 'keihin', 'kwp2000', 'k-line', '450', '500', 'exc-f', 'sx-f', 'data identifier', 'rpm', 'over-rev'],
    },
    {
      id: 'husqvarna-kmsk16-decoder', name: 'Husqvarna · Keihin KMSK16 K-Line capture decoder', category: 'diagnostics', brand: 'husqvarna',
      view: 'tools', selector: '#husqvarnaKmsk16',
      summary: 'The same Keihin KMSK16 decoder filed under Husqvarna, for the 449 and 511 that are reported to use this ECU: service decoding, identifier naming, and an explicit split between stated and inferred values.',
      steps: [
        'Paste a captured frame; the panel decodes it exactly as the KTM panel does, because it is the same decoder and the same identifier table.',
        'Confirm the ECU really is a KMSK16 before reading anything into a value. A KWP2000 answer alone does not identify the controller.',
        'Treat every number as a candidate for the source bike. The source reverse-engineered one CCM 450 Adventure and states that the Husqvarna 449/511 use the same ECU — that is a report, not a measurement on your machine.',
      ],
      caution: 'One ECU, one job set, one source with no licence file. Identifiers, ranges and enumerations were reimplemented from its published description with attribution; no code was copied, and the security-access key the source mentions is deliberately not reproduced here.',
      tags: ['husqvarna', 'husky', '449', '511', 'kmsk16', 'keihin', 'kwp2000', 'k-line'],
    },
    {
      id: 'suzuki-sds-decoder', name: 'Suzuki SDS · K-Line capture decoder', category: 'diagnostics', brand: 'suzuki',
      view: 'tools', selector: '#suzukiSds',
      summary: 'Decodes the Suzuki SDS all-sensors answer: engine speed, throttle, manifold pressure, coolant, intake air, battery voltage and the gear/status byte.',
      steps: [
        'Paste the complete 57-byte all-sensors answer, checksum included. A partial frame is refused: a checksum byte read as data is exactly how a plausible wrong value appears.',
        'Decode. Each line names the byte it came from so the arithmetic can be repeated by hand.',
        'Published SDS implementations disagree about several conversions. Where they do, the panel states which one it used rather than presenting a single number as fact.',
      ],
      caution: 'The RPM channel in this profile uses the high byte only, as its source does; other implementations compute it from two bytes and will disagree. None of these conversions is confirmed by a manufacturer document.',
      tags: ['suzuki', 'sds', 'sv650', 'k-line', 'all sensors', 'rpm', 'throttle', 'manifold'],
    },
    {
      id: 'triumph-kline-decoder', name: 'Triumph · ISO 9141 / mode 01 decoder', category: 'diagnostics', brand: 'triumph',
      view: 'tools', selector: '#triumphIso',
      summary: 'Reads a completed ISO 9141 burst from a Triumph K-Line session as SAE mode 01 data: load, coolant, fuel trim, manifold pressure, engine speed, road speed, advance, intake air and throttle.',
      steps: [
        'Paste one complete burst: 48 6B D1 41 <pid> <data> <checksum>.',
        'The header and the summing checksum are verified first. A burst that fails either is rejected, not partially decoded.',
        'Only positive 0x41 answers are interpreted. A negative answer (0x7F) is reported as a refusal and no value is invented from it.',
        'Cross-check a decoded PID against a second, independent channel before you trust a single reading.',
      ],
      caution: 'The framing and the PID formulas come from daytona-kline, tested by its author on one 2012 Daytona 675. PIDs that a Triumph must answer are not listed anywhere here: an answer proves the PID exists on that ECU, nothing more.',
      tags: ['triumph', 'daytona', '675', 'iso 9141', 'iso9141', 'k-line', 'mode 01', 'pid'],
    },
    {
      id: 'bmw-can-decoder', name: 'BMW Motorrad · 11-bit CAN decoder', category: 'telemetry', brand: 'bmw',
      view: 'tools', selector: '#bmwCan',
      summary: 'Decodes the three BMW broadcast frames one public source describes: engine speed, high-beam flash state and the switch-cluster bits for left, right and brake.',
      steps: [
        'Paste one 11-bit data frame per line: 10C#0011223344556677.',
        'Press Decode. Unknown identifiers and payloads shorter than the layout needs are rejected rather than guessed at.',
        'Read the bits as candidates. A switch bit that reads 1 says a bus message carried that bit, not that the switch works.',
      ],
      caution: 'EasierCan records these frames on an R1300GS and does not state the direction of each message, so a bit could be an input, a status echo or another controller’s report. The source names no other model year.',
      tags: ['bmw', 'motorrad', 'r1300gs', 'can', '11-bit', 'switch', 'high beam'],
    },
    {
      id: 'ducati-can-decoder', name: 'Ducati Panigale · Mitsubishi CAN decoder', category: 'telemetry', brand: 'ducati',
      view: 'tools', selector: '#ducatiCan',
      summary: 'Interprets the three 11-bit frames of the Panigale Mitsubishi layout: rear wheel speed and the raw gear byte, throttle and engine speed, temperatures and battery voltage.',
      steps: [
        'Paste candump lines — can0 080#0011223344556677 or can0 18 [8] … — one frame per line.',
        'Extended identifiers are refused: this layout describes 11-bit frames only, and a 29-bit ID at the same numeric value is a different message.',
        'Read the temperatures as signed: the offset is −40 °C, so a cold engine reads below zero rather than wrapping.',
        'The gear byte is printed raw. The source does not map it to a gear number, so do not infer one.',
      ],
      caution: 'The layout comes from DucatiPanigaleCanBus, one reverse-engineered Mitsubishi bus. Wheel speed, throttle and battery are candidates for that bike; nothing here identifies a Panigale model or year.',
      tags: ['ducati', 'panigale', 'mitsubishi', 'can', '11-bit', 'gear', 'wheel speed'],
    },
    {
      id: 'indian-j1939-decoder', name: 'Indian · J1939 broadcast decoder', category: 'telemetry', brand: 'indian',
      view: 'tools', selector: '#indianJ1939',
      summary: 'Reads five J1939 PGNs: EEC1 engine speed and demand, ET1 cylinder-head temperature, CCVS rear speed, the dash fuel level and the front wheel-speed PGN, printing the PGN, its name and the source address.',
      steps: [
        'Paste candump lines with 29-bit identifiers and exactly eight data bytes.',
        'Decode. The header line names the PGN and the source address the profile expects, so a frame from a different controller is obvious rather than silently wrong.',
        'A PGN the source describes but from another source address is reported with both addresses named: one bike, one address table.',
        '0xFF and 0xFFFF mean “not available” and are printed as such, not as a value.',
      ],
      caution: 'One 2017 Springfield, integration-tested with synthetic frames only. The bike is air-cooled, so the temperature channel is cylinder head, not coolant — reading it as coolant misreports the engine.',
      tags: ['indian', 'springfield', 'j1939', 'pgn', 'can', 'eec1', 'ccvs', 'fuel'],
    },

    /* ------------------------------------------- IAW image layout */
    {
      id: 'iaw-image-layout', name: 'Moto Guzzi · IAW image layout & definition fit', category: 'calibration', brand: 'moto-guzzi',
      view: 'tools', selector: '#iawGuzziPanel',
      summary: 'Answers two questions before you trust a dump: where the file sits inside the image, and whether the definition you picked actually describes tables that are inside those bytes.',
      steps: [
        'Pick the geometry, or type the base yourself. The 5AM flash region 0x4000–0x50000 (311,296 bytes of a 320 KiB image) is the same constant the catalog and the programming gate use.',
        'Choose the image, or type its size if you only have a region.',
        'Pick a definition from the library — the list is read from the bundled XDF index, so it is the same set the Maps view offers.',
        'Press Check the fit. Tables inside the file are listed with their file offsets; tables outside are listed with the reason.',
        'Read the verdict as a size check, not a fitment check. A file big enough for a definition is not proof that the definition belongs to this ECU: a definition from another family can describe plausible tables at the wrong addresses.',
      ],
      caution: 'Sizes are rows × columns × resolution: a table with a non-standard stride can be slightly larger in reality. The tool reports addresses from the definition and never reads a calibration value, so it cannot tell you what a byte means.',
      tags: ['iaw', '5am', 'moto guzzi', 'image', 'layout', 'offset', 'xdf', 'fit', 'definition'],
    },
    {
      id: 'aprilia-image-layout', name: 'Aprilia · IAW / MIU G3 image layout & definition fit', category: 'calibration', brand: 'aprilia',
      view: 'tools', selector: '#iawApriliaPanel',
      summary: 'The same definition-fit check for the Aprilia side of the library: 15P, 5AM, 7SM and MIU G3 definitions, matched against the bytes you actually have.',
      steps: [
        'Set the base offset. For a 5AM-family Aprilia the flash region starts at 0x4000, exactly as on the Guzzi side.',
        'Choose the image or type its size, then pick the definition.',
        'Press Check the fit and read the two lists: what falls inside the file, and what does not and why.',
        'Compare the highest address the definition uses with the size of your read. If the definition needs more, you have a partial read.',
      ],
      caution: 'The Aprilia 7SM and MIU G3 catalog entries are identification-only: the program has no verified flash geometry for them, so this tool makes no claim about where their flash starts. Reading a definition is not programming authorization.',
      tags: ['aprilia', 'iaw', '15p', '5am', '7sm', 'miu g3', 'image', 'layout', 'xdf'],
    },

    /* ------------------------------------------- bench calculators */
    {
      id: 'injector-panel', name: 'Injector & fuel-flow calculator', category: 'calibration',
      view: 'tools', selector: '#injectorPanel',
      summary: 'Turns a target power into the fuel volume and injector size that would deliver it — or the injectors you already have into a duty cycle — with pressure, fuel and injection-window arithmetic shown.',
      steps: [
        'Enter the target crank power, the BSFC assumption, the injector count and the maximum duty you are willing to run.',
        'Pick the fuel. Compared with petrol, E85 needs about 1.4 times the volume for the same lambda, and the calculator applies that through the stoichiometric ratio and density rather than a fudge factor.',
        'Set the fuel pressure you will run and the pressure the injector was rated at. Flow scales with the square root of the pressure difference, so the two are not interchangeable.',
        'If you already have injectors, type their rated flow: the panel prints the duty cycle at the same target and warns when it cannot reach it.',
        'The rpm field turns the cycle time into an injection window and shows the pulse width at your duty limit.',
      ],
      caution: 'BSFC decides the answer, and 0.50 lb/(hp·h) is an assumption for a naturally aspirated four-stroke at peak power — an air-cooled two-valve twin can be worse. Vendor flow figures are quoted at a stated pressure with a test fluid. Measure duty cycle on the bike before buying anything.',
      tags: ['injector', 'sizing', 'bsfc', 'duty cycle', 'fuel flow', 'e85', 'pressure', 'pulse width'],
    },
    {
      id: 'dyno-correction', name: 'Dyno correction & air density', category: 'telemetry',
      view: 'tools', selector: '#dynoCorrectionPanel',
      summary: 'Corrects a measured power figure to a standard reference air and shows the same run under SAE J1349, DIN 70020, SAE J607, ISO 1585 and uncorrected, with dry pressure, vapour pressure and density shown.',
      steps: [
        'Enter the measured figure and its unit. The corrected number comes back in the same unit — nothing is converted behind your back.',
        'Give the conditions: air temperature, barometric pressure and relative humidity. Clear the pressure field to have it estimated from an altitude instead; when both are present the measured pressure wins.',
        'Read the factor for the chosen standard and the table beside it, which shows every standard for the same run. A different standard on the same data routinely moves the number by several percent.',
        'Watch the density ratio: it is the physical reason the correction exists, and it is what to quote when you do not want to claim a standard.',
      ],
      caution: 'SAE J1349 is defined for naturally aspirated engines. A boosted engine is flagged rather than corrected silently. Correction cannot fix a heat-soaked intake, wheelspin on the drum or an inconsistent throttle ramp — quote the standard with the figure.',
      tags: ['dyno', 'correction factor', 'sae j1349', 'din 70020', 'sae j607', 'iso 1585', 'air density', 'altitude', 'humidity'],
    },
    {
      id: 'fuel-blend', name: 'Fuel blend, λ & stoichiometry', category: 'calibration',
      view: 'tools', selector: '#fuelBlendPanel',
      summary: 'Converts between lambda and AFR for any ethanol blend and shows what the blend does to stoichiometry, density, energy per litre and the fuel volume the same lambda needs.',
      steps: [
        'Set the ethanol percentage, then choose whether the number you have is lambda or AFR.',
        'Read the blend: stoichiometric ratio, density, energy per litre, and the AFR that lambda corresponds to on this blend and on petrol.',
        'Tick through the comparison table for E0, E10, E85 and E100: the volume column is how much more fuel the same lambda needs, which is what breaks injector sizing when a bike changes fuel.',
        'If you know the petrol duty cycle you run now, type it: the panel prints the duty the same injectors would see on this blend and warns past the linear range.',
      ],
      caution: 'The blend is a model, not a measurement: pump E10 can be E5–E15 and winter E85 is nearer E50–E70. Lambda is what the engine responds to; AFR figures from two logs are only comparable when the assumed stoichiometric ratio is the same. This is not a mixture recommendation.',
      tags: ['lambda', 'afr', 'e85', 'e10', 'stoich', 'ethanol', 'methanol', 'fuel volume', 'injector duty'],
    },
    {
      id: 'canlog-analyzer', name: 'CAN identifier discovery (offline analyzer)', category: 'telemetry',
      view: 'discovery', selector: '#canlogText',
      summary: 'Finds likely request/response identifier pairs and per-byte statistics in an existing CAN capture; the workstation never generates bus traffic here.',
      steps: [
        'Paste a capture or load a local file.',
        'Optionally filter by identifier and enable byte statistics.',
        'Press Analyze; read candidate pairs and byte ranges.',
      ],
      tags: ['can', 'identifier', 'analyzer', 'capture', 'byte stats', 'iso-tp'],
    },
    {
      id: 'hdlan-observe', name: 'Motorcycle CAN · live broadcast observation', category: 'telemetry',
      view: 'discovery', selector: '#harleyLiveCan',
      summary: 'Observe candidate broadcast values on an already configured Linux SocketCAN interface for a selected source profile (Ducati, Yamaha R9, Harley HD-LAN and others).',
      steps: [
        'Configure the SocketCAN interface and bitrate outside the app.',
        'Select the source profile, tick the confirmation and press Start.',
        'Read candidate values with the profile’s caveats; mappings vary by model/year.',
      ],
      tags: ['can', 'hdlan', 'harley', 'broadcast', 'socketcan', 'observe'],
    },
    {
      id: 'yamaha-kline-observe', name: 'Yamaha MT-03 dashboard-stream observation', category: 'telemetry',
      view: 'discovery', selector: '#yamahaLiveKline',
      summary: 'Observe one two-second window of the existing dashboard/ECU K-Line stream at 16064 baud using a Linux FTDI KKL adapter.',
      steps: [
        'Disconnect any active ECU session first.',
        'Enter the adapter port and tick the confirmation.',
        'Press Observe; the panel decodes candidate dashboard fields.',
      ],
      tags: ['yamaha', 'mt-03', 'kline', 'dashboard', 'observe', '16064'],
    },
    {
      id: 'kline-discovery', name: 'K-Line identifier discovery', category: 'diagnostics',
      view: 'discovery', selector: '#klinelogText',
      summary: 'Analyze a K-Line capture against a family reference: the 5AM table is capture-verified, 16M has documented legacy registers, 7SM has identification only.',
      steps: [
        'Select the ECU family and load or paste the capture.',
        'Optionally supply a reference table file.',
        'Analyze to see which identifiers are recognised and which remain unknown.',
      ],
      tags: ['kline', 'discovery', 'identifiers', '5am', '16m', 'capture'],
    },
    {
      id: 'replay-panel', name: 'Replay & session compare', category: 'dash',
      view: 'sessions', selector: '#replayPanel',
      summary: 'Scrub a recording with derived values recomputed from the recorded bytes, and compare two sessions to see what changed.',
      steps: [
        'Load a session from the list.',
        'Scrub the timeline or press play; findings recompute at each point.',
        'Pick two sessions under Compare two sessions and read the channel deltas.',
      ],
      tags: ['replay', 'session', 'compare', 'scrub', 'timeline'],
    },
    {
      id: 'report-panel', name: 'Service report builder', category: 'workshop',
      view: 'report', selector: '#buildReportBtn',
      summary: 'Builds a printable/shareable report of identification, fault codes, live values and every safety decision in the session.',
      steps: [
        'Press Build report after gathering the data you need.',
        'Download .txt or .json, or print the view to PDF.',
        'Reports list refusals too — that is the safety record.',
      ],
      tags: ['report', 'print', 'pdf', 'export', 'safety record'],
    },
  ];

  window.GOB_HELP = {
    version: '1.1.0',
    categories: CATEGORIES,
    brands: BRANDS,
    tools: TOOLS,
  };
}());

/* ======================================================================
 * PROTOCOLS — one article per wire protocol / bus / transport.
 * Rendered at #help/protocol/<id> with a specification table.
 * ==================================================================== */
(function () {
  'use strict';

  const PROTOCOLS = [
    {
      id: 'kwp2000',
      name: 'KWP2000 on K-Line (ISO 14230)',
      short: 'The main motorcycle diagnostic protocol in this program: a single-wire 12 V bus with fast or 5-baud initialisation and checksum-protected frames.',
      transport: 'K-Line — one bidirectional 12 V wire plus ground, pulled up by the interface.',
      baud: '10,400 baud for most profiles; some ECUs switch to a higher rate after initialisation.',
      init: 'Fast init (ISO 14230-2) or 5-baud init. Selected explicitly in the Garage, or automatically.',
      addressing: 'Physical addressing with tester 0xF1 and ECU 0x10 for IAW 5AM / 7SM; functional 0x33 only where a profile proves it.',
      framing: 'Format/length byte, target, source, service, data…, checksum (CS).',
      checksum: 'A one-byte additive checksum per frame. It is not the calibration checksum inside the flash image.',
      body: `
<h3>Fast initialisation (the usual path)</h3>
<ol>
  <li>Bus idle for <b>W5 / Tidle = 300 ms</b> — the workstation waits before its first attempt.</li>
  <li>Pull K-Line low for <b>TiniL = 24–26 ms</b>.</li>
  <li>Release at <b>TWuP = 49–51 ms</b> from the first falling edge and immediately send StartCommunication.</li>
  <li>The first message carries target and source addresses — no separate length byte.</li>
  <li>Accept the link only for a checksum-valid positive <code>C1</code> response carrying two key bytes.</li>
</ol>
<p>Noise, an echo, a truncated frame, a bad checksum or an unrelated positive response is <b>not</b> successful initialisation. The workstation validates all of it and reports every automatic attempt on the Link card.</p>

<h3>5-baud initialisation</h3>
<table class="help-table"><thead><tr><th>Symbol</th><th>Timing</th><th>Meaning</th></tr></thead><tbody>
<tr><td>W5</td><td>≥ 300 ms</td><td>idle before the address</td></tr>
<tr><td>bit time</td><td>200 ms</td><td>5-baud address: start, eight LSB-first bits, stop</td></tr>
<tr><td>W1</td><td>60–300 ms</td><td>address end to <code>55</code> sync</td></tr>
<tr><td>W2</td><td>5–20 ms</td><td>sync to KW1</td></tr>
<tr><td>W3</td><td>0–20 ms</td><td>KW1 to KW2</td></tr>
<tr><td>W4</td><td>25–50 ms</td><td>KW2 → tester’s <code>~KW2</code> → ECU’s <code>~address</code></td></tr>
</tbody></table>
<p>A successful 5-baud handshake establishes communication by itself; <b>StartCommunication must not follow it</b>. ISO 9141-2 looks electrically identical but selects a different message protocol through its keywords — the workstation identifies and reports that result instead of treating it as KWP2000.</p>

<h3>Sessions and keep-alive</h3>
<p>IAW 5AM enters diagnostic session <code>0x81</code>; it rejects <code>0x85</code> with NRC <code>0x22</code> outside the programming flow. Sessions are opened lazily — only when a service needs one — and a TesterPresent keeps them alive (typically every 2 s). A dropped session mid-read is one of the classic causes of a failed memory dump.</p>

<h3>Where this program uses it</h3>
<ul>
  <li><b>IAW 5AM / 5AM2</b>: identification, live data, DTCs, actuator tests, resets, 19-block flash reads, SecurityAccess and the gated write path.</li>
  <li><b>IAW 7SM</b>: identification and session handling (memory access is not implemented).</li>
  <li><b>Suzuki SDS, Kawasaki KDS, Triumph and Honda</b>: family-specific K-Line variants, some using OBD services over the same wire.</li>
</ul>

<h3>Typical failures</h3>
<ul>
  <li><b>No response to fast init</b>: wrong port, no K-Line transceiver, ignition off, or a 5-baud-only ECU — try the other init method.</li>
  <li><b>Link drops during a read</b>: adapter latency timer (set 1 ms), USB power saving, or a session that timed out because TesterPresent stopped.</li>
  <li><b>Checksum errors on every frame</b>: echo not suppressed by the interface, or the wrong baud rate.</li>
</ul>`,
      usedBy: ['IAW 5AM / 5AM2', 'IAW 7SM', 'Suzuki SDS', 'Kawasaki KDS', 'Triumph (OBD over K-Line)', 'Honda PGM-FI'],
      workstation: ['Garage → transport K-Line', 'Garage → init method', 'Overview → Link', 'Firmware → Adapter pre-flight'],
      tags: ['kwp2000', 'iso 14230', 'kline', 'k-line', 'fast init', '5 baud', 'startcommunication', 'c1', 'checksum', 'session'],
      related: ['protocol-iso9141', 'protocol-legacy-iaw', 'howto-first-connection'],
    },
    {
      id: 'kmsk16',
      name: 'Keihin KMSK16 (KTM, Husqvarna 449/511, CCM 450)',
      short: 'A Keihin ECU that speaks ordinary KWP2000 over K-Line at 10,400 baud, with Keihin\'s own data identifiers rather than SAE PIDs.',
      transport: 'K-Line — one 12 V wire, driven through an L9637D transceiver in the reference implementation.',
      baud: '10,400 baud, fixed in the published implementation.',
      init: 'Fast init: a 25 ms low half-period, then StartCommunication. No 5-baud handshake is described.',
      addressing: 'Physical addressing: format byte 0x80, target 0x12 (ECU), source 0xF1 (tester).',
      framing: 'Format/length byte, target, source, service, data…, one-byte additive checksum — the same frame as the KWP2000 article.',
      checksum: 'One-byte sum of every preceding byte. The ECU rejects a response whose sum does not match, and so does this program.',
      body: `
<h3>What makes it different from the IAW K-Line profiles</h3>
<p>The wire and the framing are ordinary KWP2000. What is not ordinary is the <b>data identifier table</b>: Keihin numbers its own channels, so <code>0x0100</code> is engine speed and <code>0x0009</code> is coolant temperature, and none of them is an SAE PID. Reading live data therefore means knowing the table, not sending <code>01 0C</code>.</p>

<h3>Services the published job set uses</h3>
<table class="help-table"><thead><tr><th>Service</th><th>Name</th><th>What this program does with it</th></tr></thead><tbody>
<tr><td><code>0x81</code></td><td>StartCommunication</td><td>decoded from a capture only</td></tr>
<tr><td><code>0x10 / 0x11 / 0x14</code></td><td>session, ECU reset, clear faults</td><td>named, never sent</td></tr>
<tr><td><code>0x18</code></td><td>ReadDTCByStatus</td><td>named, never sent</td></tr>
<tr><td><code>0x22</code></td><td>ReadDataByCommonIdentifier</td><td><b>decoded</b> — this is the live-data path</td></tr>
<tr><td><code>0x27</code></td><td>SecurityAccess</td><td>recognised; the key is not in this project</td></tr>
<tr><td><code>0x31 / 0x32</code></td><td>start / stop routine</td><td>names and results decoded, nothing started</td></tr>
<tr><td><code>0x3E</code></td><td>TesterPresent</td><td>recognised</td></tr>
</tbody></table>

<h3>The identifiers worth knowing</h3>
<ul>
  <li><b>Engine speed <code>0x0100</code></b> — a 16-bit value, high byte first, declared 0–16384 rpm. A quarter-rpm resolution follows from the range; the source does not state it, so the panel labels the number <b>inferred</b>.</li>
  <li><b>Coolant and intake air <code>0x0009 / 0x0011</code></b> — declared −40…215 °C, which is a 255-count span, so the panel reports one degree per count with a −40 offset and says that the second received byte is unexplained.</li>
  <li><b>Calculated load <code>0x0107</code></b> — the source gives a formula, not a scaling, and never says which identifier supplies PM1M. The panel prints the formula and refuses to invent the input.</li>
  <li><b>Second throttle <code>0x0170</code></b> — needs <code>0x0172</code> and <code>0x0173</code> as well. Paste all three and the panel derives the percentage, labelled as a rewritten formula because the source divides by a ratio of two A/D values.</li>
  <li><b>Over-rev counters <code>0x0500–0x0510</code></b> — the source gives one range in the job entry and another in its identifier summary. The panel shows the raw value and both readings.</li>
</ul>

<h3>Routines that answer a question without changing anything</h3>
<p><code>$31</code> with local identifier <code>0x0102</code> (application code) or <code>0x0104</code> (calibration data) runs the ECU's own <b>CheckCodingChecksum</b>. That is the only read-only way this ECU offers to say whether a calibration is internally consistent, and it is why the routine names are in the decoder even though nothing here starts a routine.</p>

<h3>What is deliberately absent</h3>
<ul>
  <li><b>The security-access key</b> — obtained in the source by brute force, supplier-specific, and not reproduced here. Reading may require it on some model years; this project does not attempt the read.</li>
  <li><b>Any programming sequence</b> — the job set names erase, download, transfer and rewrite services. A name is not a verified sequence, and this repository implements none of them for this ECU.</li>
  <li><b>Any physical validation</b> — the whole table comes from one reverse-engineered bike. It is evidence of what one ECU answered, not a fitment claim for a given machine.</li>
</ul>`,
      usedBy: ['KTM 450/500 four-stroke generation', 'Husqvarna 449 / 511', 'CCM 450 Adventure'],
      workstation: ['Tools → KTM → KMSK16 capture decoder', 'Tools → Husqvarna → KMSK16 capture decoder'],
      tags: ['kmsk16', 'keihin', 'ktm', 'husqvarna', 'ccm', 'kwp2000', 'k-line', '10400', 'data identifier', 'checksum'],
      related: ['protocol-kwp2000', 'tool-ktm-kmsk16-decoder'],
    },
    {
      id: 'iso9141',
      name: 'ISO 9141-2 (OBD on K-Line)',
      short: 'Electrically identical to 5-baud KWP initiation but a different message protocol, selected by the ECU’s keyword bytes.',
      transport: 'K-Line, 12 V, single wire. Optionally a second L-line on cars (not used on these bikes).',
      baud: '10,400 baud after the 5-baud address phase.',
      init: '5-baud only. Keywords <code>08 08</code> or <code>94 94</code> choose ISO 9141-2 instead of KWP2000.',
      addressing: 'OBD functional/physical addressing with the 5-byte header, or headerless mode where the profile specifies it.',
      framing: 'ISO 9141-2 header (priority, target, source), length, service, data, checksum (or none where configured).',
      checksum: 'Additive checksum per message in the standard configuration.',
      body: `
<h3>Why it is a separate protocol here</h3>
<p>A 5-baud handshake can end in either KWP2000 or ISO 9141-2 depending on the two keyword bytes the ECU returns. Treating them as interchangeable is a common bug in hobby tools: the link “succeeds” and then every request is silently wrong. The workstation reads the keywords, names the protocol it actually negotiated, and reports when a KWP2000 profile received ISO 9141-2 keywords.</p>

<h3>What is implemented</h3>
<ul>
  <li><b>2009 Triumph Bonneville 865 EFI</b> — read-only OBD mode 01 PIDs and stored mode 03 faults (source-reported; synthetic tests only).</li>
  <li><b>2012 Triumph Daytona 675</b> — the same read-only OBD surface.</li>
  <li>Identification, DTC clears, memory reads and programming are <b>not</b> offered for these profiles.</li>
</ul>

<h3>Practical notes</h3>
<ul>
  <li>Many ELM327-style adapters implement ISO 9141-2 badly or not at all; they are a different code path from the KKL/FTDI interfaces this program drives directly.</li>
  <li>Only PIDs the profile declares are requested. Unsupported PIDs are not guessed from the model name.</li>
  <li>Gauge formulas come from the SAE definitions and are not compared against the motorcycle’s dash.</li>
</ul>`,
      usedBy: ['2009 Triumph Bonneville 865 EFI', '2012 Triumph Daytona 675'],
      workstation: ['Garage → transport K-Line', 'Overview → Link', 'Live data'],
      tags: ['iso 9141', 'obd', 'kline', 'keywords', '5 baud', 'triumph', 'mode 01'],
      related: ['protocol-kwp2000', 'ecu-triumph-other'],
    },
    {
      id: 'legacy-iaw',
      name: 'Marelli legacy IAW (pre-KWP2000)',
      short: 'The older Marelli diagnostic protocol used by the IAW 16M: a slow key-on initialisation followed by echoed single-byte register queries.',
      transport: 'K-Line, 12 V.',
      baud: '1,200 baud for initialisation, then 7,680 baud for communication (16M).',
      init: 'Key-on legacy initialisation with an 8 s wake-up timeout — not a KWP2000 frame exchange.',
      addressing: 'Byte-register queries with an echoed response; no target/source header.',
      framing: 'Single-byte commands with a mirrored reply; separate fault registers.',
      checksum: 'None at the frame layer; the ECU answers with the register value.',
      body: `
<h3>How it works</h3>
<p>The IAW 16M (Sport 1100, V10 Centauro, Daytona RS) predates KWP2000. The workstation initialises at 1,200 baud, switches to 7,680 baud, then asks for individual registers by number. The evidence base is the Marelli 3.00600 / 16F technical publication, a published 1.6M open implementation, IAW Scan 2’s independent 16F implementation and ScanST’s tested Moto Guzzi 16M support.</p>

<h3>Deliberate limits</h3>
<ul>
  <li>Temperature scaling differs between sources (−40 °C in the 16F publication, −55 °C in the recovered implementation), so those channels are exposed as <b>raw counts</b> rather than a guessed temperature.</li>
  <li>Active-test, clear-errors and reset bytes are known but not exposed: they are ECU-timed single-byte commands that do not fit the workstation’s explicit on/off safety contract.</li>
  <li>No in-circuit memory access exists. 16M maps normally live in a socketed EPROM — read it with an EPROM programmer and keep the original chip.</li>
</ul>`,
      usedBy: ['IAW 16M (Sport 1100, Centauro, Daytona RS)'],
      workstation: ['Garage → transport K-Line', 'Live data', 'Fault codes'],
      tags: ['legacy iaw', '16m', 'marelli', 'register', '1200 baud', '7680', 'eprom'],
      related: ['protocol-kwp2000', 'ecu-iaw-family'],
    },
    {
      id: 'can-iso-tp',
      name: 'CAN with ISO-TP (ISO 15765-2) and UDS / KWP-on-CAN',
      short: 'Classic CAN at 500 kbit/s carrying segmented diagnostic messages, usually UDS (ISO 14229) or KWP2000 services on CAN identifiers.',
      transport: 'Classic CAN (11-bit IDs on these profiles), twisted pair, 120 Ω termination.',
      baud: '500 kbit/s for every CAN profile bundled here.',
      init: 'No 5-baud handshake: the interface is configured for bitrate and the first diagnostic request opens the conversation.',
      addressing: 'A request identifier and a response identifier per ECU (e.g. 0x7E0 → 0x7E8, or a manufacturer pair such as 0x764 → 0x746).',
      framing: 'ISO-TP PCI bytes: single frame, first frame, consecutive frame, flow control.',
      checksum: 'CAN CRC at the link layer; ISO-TP has no per-message additive checksum.',
      body: `
<h3>Interfaces this program can drive</h3>
<ul>
  <li><b>SLCAN</b> serial CAN adapters (Lawicel-style ASCII protocol).</li>
  <li><b>Linux SocketCAN</b> interfaces (<code>can0</code>), configured outside the app with <code>ip link</code> and the right bitrate.</li>
  <li><b>PEAK PCAN</b> USB interfaces with the vendor driver.</li>
  <li><b>J2534 pass-thru</b> devices, enumerated through an installed vendor DLL — used for interface discovery and supported sessions only.</li>
  <li><b>Intrepid</b> hardware, where the optional extra is installed.</li>
</ul>

<h3>Why a CAN identifier pair is not a protocol</h3>
<p>ISO-TP only moves bytes. It does not tell you whether the ECU speaks UDS, KWP-on-CAN, or a proprietary dialect, and it does not reveal which services exist. Every CAN profile in the catalog therefore states its own evidence and refuses physical sessions where the identifiers or payloads were never captured. The offline <b>CAN identifier discovery</b> analyzer can suggest candidate pairs in a capture you already have, but the workstation never generates bus traffic to find them.</p>

<h3>Profiles here</h3>
<ul>
  <li><b>Harley Delphi CAN identity</b> — 500 kbit/s, 0x7E0/0x7E8, identity and live research only.</li>
  <li><b>Kawasaki Ninja 7 Hybrid</b> — KWP-on-CAN, 0x764/0x746, identify/live/DTC research.</li>
  <li><b>Generic OBD-II 11-bit CAN</b> — standard OBD modes only, opt-in, no memory access.</li>
  <li><b>Marelli 11MP, MIU G4 and several 2023+ Kawasaki models</b> — catalogued, but no trustworthy identifier pair, so physical sessions are blocked.</li>
</ul>

<h3>Safety</h3>
<p>Do not connect a CAN interface to a bike whose bus you have not identified, and never bridge CAN to a bench supply without termination. A wrong bitrate produces error frames, not useful data.</p>`,
      usedBy: ['Harley Delphi CAN', 'Kawasaki Ninja 7 Hybrid', 'Generic OBD-II CAN', 'Marelli 11MP', 'MIU G4'],
      workstation: ['Garage → transport CAN', 'Garage → CAN interface', 'Discovery → CAN identifier discovery', 'Discovery → live broadcast observation'],
      tags: ['can', 'iso-tp', 'iso 15765', 'uds', 'iso 14229', 'socketcan', 'slcan', 'pcan', 'j2534', '7e0', '7e8', 'bitrate'],
      related: ['protocol-j1850', 'protocol-hdlan', 'protocol-kwp2000'],
    },
    {
      id: 'j1850',
      name: 'SAE J1850 VPW via ELM327',
      short: 'The separate Harley-Davidson read-only research path: a serial ELM interface that explicitly supports J1850 VPW at 38,400 baud.',
      transport: 'J1850 VPW (variable pulse width), 12 V, single wire — not K-Line and not CAN.',
      baud: 'ELM327 serial link at 38,400 baud; the bus itself is pulse-width modulated.',
      init: 'ELM327 protocol selection for J1850 VPW; no KWP handshake is possible or attempted.',
      addressing: 'OBD-style headers handled by the ELM firmware.',
      framing: 'ELM ASCII command/response, then J1850 frames.',
      checksum: 'J1850 CRC inside the frame, computed by the adapter/ECU.',
      body: `
<h3>What it is for</h3>
<p>Older Harley-Davidson Delphi ECUs use J1850 VPW, not K-Line. The <b>Harley-Davidson J1850 VPW (HarleyDroid)</b> profile performs identification, live reads and DTC reads through an ELM interface that supports VPW. It is read-only research: HarleyDroid-style diagnostic queries cannot read or program the calibration.</p>

<h3>Choosing an adapter</h3>
<p>Many ELM327 clones advertise OBD-II but do not implement J1850 VPW at all. Check the datasheet for explicit VPW support before buying. This path is completely separate from the KKL/FTDI K-Line interface and cannot be substituted for it.</p>

<h3>Limits</h3>
<ul>
  <li>No ECU memory read, no programming, no checksum provider.</li>
  <li>Compatibility varies by model year and ECU; the profile is synthetic-tested only.</li>
  <li>For CAN-era Harleys use the Delphi CAN profile and a SocketCAN interface instead.</li>
</ul>`,
      usedBy: ['Harley-Davidson J1850 VPW (HarleyDroid)'],
      workstation: ['Garage → transport ELM / J1850', 'Live data', 'Fault codes'],
      tags: ['j1850', 'vpw', 'elm327', 'harley', 'harleydroid', 'obd'],
      related: ['protocol-can-iso-tp', 'ecu-harley-family'],
    },
    {
      id: 'hdlan',
      name: 'HD-LAN and broadcast CAN observation',
      short: 'Listen-only observation of the motorcycle’s normal broadcast traffic — no requests, no writes, and mappings are best-effort.',
      transport: 'Classic CAN, 500 kbit/s on the bundled profiles.',
      baud: '500 kbit/s (Ducati and Yamaha R9 sources), others as stated by the profile.',
      init: 'None — receive-only. The interface is configured outside the app.',
      addressing: 'Broadcast identifiers defined by the source profile.',
      framing: 'Raw CAN frames decoded per profile.',
      checksum: 'None applied — values are candidate interpretations of live bytes.',
      body: `
<h3>What you get</h3>
<p>The <b>Motorcycle CAN · live broadcast observation</b> panel (Discovery) listens to an already configured SocketCAN interface for a two-second window and decodes candidate values for the selected profile: Ducati Panigale, Yamaha R9, Harley HD-LAN and others. This is observation of the bike’s own traffic — the workstation transmits nothing.</p>

<h3>Preconditions</h3>
<ul>
  <li>Bring the interface up yourself, with the correct bitrate and termination.</li>
  <li>Disconnect any active ECU session first; two readers on one bus is a support nightmare.</li>
  <li>Tick the confirmation acknowledging that mappings are best-effort and vary by model/year.</li>
</ul>

<h3>Interpreting results</h3>
<p>Byte positions and scalings come from third-party research. Treat every number as a candidate: check it against a value you already know (idle RPM, battery voltage at rest) before relying on it. <b>Byte statistics</b> in the offline analyzer help you see which bytes actually move before you trust a field.</p>`,
      usedBy: ['Ducati Panigale (research)', 'Yamaha R9 2026 (research)', 'Harley HD-LAN'],
      workstation: ['Discovery → Motorcycle CAN observation', 'Discovery → CAN identifier discovery'],
      tags: ['hdlan', 'harley', 'broadcast', 'can', 'observe', 'ducati', 'yamaha r9', 'listen'],
      related: ['protocol-can-iso-tp', 'protocol-j1850'],
    },
    {
      id: 'kds-sds',
      name: 'Kawasaki KDS and Suzuki SDS K-Line variants',
      short: 'Family-specific K-Line dialects used by Kawasaki and Suzuki service tools: same wire as KWP2000, different request/response shapes.',
      transport: 'K-Line, 12 V, 10,400 baud on the bundled profiles.',
      baud: '10,400 baud.',
      init: 'Family-specific (e.g. <code>suzuki-sds-gsxr-research</code>), not ISO 14230 fast init.',
      addressing: 'Raw snapshots with family-specific request bytes.',
      framing: 'Fixed request with a long (≈50-byte) response snapshot.',
      checksum: 'Family-specific; not validated by this implementation.',
      body: `
<h3>Status in this catalog</h3>
<p>Several Kawasaki KDS and Suzuki SDS profiles provide <b>live raw snapshots only</b>: one documented request returns a fixed block of bytes, and the workstation exposes the decoded candidates. ECU identity, fault codes, memory access and programming are not implemented, and physical use is research-only.</p>

<h3>Profiles</h3>
<ul>
  <li><b>Suzuki</b>: GSX-R / Hayabusa SDS research, SV650 2003–2005, SV650AK7 2007, GSX-R600 2011, GSX-R1000 2004, V-Strom DL650 2017, plus an ECU-only generic attempt.</li>
  <li><b>Kawasaki</b>: ER-6n 2006, Versys 650 2012, KDS generic research, and 2023–2026 Ninja 650 / Z650 / ZX-6R CAN research entries.</li>
</ul>

<h3>Honesty rules</h3>
<p>“Compatible with KDS” is not a protocol definition. Where only a compatibility list exists, the catalog entry has zero capabilities and physical use is refused. Where a source implementation exists, the profile says so and is marked synthetic-tested only — never bench-confirmed by this project.</p>`,
      usedBy: ['Suzuki SDS profiles', 'Kawasaki KDS profiles'],
      workstation: ['Garage → transport K-Line', 'Live data', 'Raw provenance'],
      tags: ['kawasaki', 'kds', 'suzuki', 'sds', 'kline', 'raw snapshot'],
      related: ['protocol-kwp2000', 'ecu-suzuki-kawasaki'],
    },
    {
      id: 'honda-pgmfi',
      name: 'Honda Keihin PGM-FI K-Line',
      short: 'Honda’s Keihin K-Line dialect, with an offline response decoder and a source-scoped calibration checksum helper.',
      transport: 'K-Line, 12 V, 10,400 baud.',
      baud: '10,400 baud.',
      init: '<code>honda-pgmfi-research</code> family initialisation.',
      addressing: 'Family-specific headers; complete frames are required for the decoder.',
      framing: 'Length-prefixed frames with a trailing checksum byte.',
      checksum: 'Additive frame checksum (validated by the offline decoder); calibration sums are a separate mechanism.',
      body: `
<h3>Live path</h3>
<p>The <b>Honda Keihin PGM-FI K-Line (research)</b> profile offers identification and live data only. Several Honda entries in the catalog (CB500F DashBle, CTX700, CBR600RR 2005, CBR1000RR 2012 US, CB500 MGZ-A03) are source-scoped, and some have no wire definition at all — those refuse physical sessions.</p>

<h3>Offline decoder</h3>
<p>Tools → <b>Honda K-Line · offline response decoder</b> accepts complete hex frames, one per line, and decodes them with a third-party implementation tested by its author on a 2005 CBR600RR. A frame with a bad checksum is refused rather than guessed. Results are candidates, not vehicle identification.</p>

<h3>Calibration checksums</h3>
<p>Honda calibration checksums are handled separately by the <b>Honda source-ID · calibration checksum</b> tool and the two bundled, explicitly selected checksum providers (CBR1000RR 2012 US / 38770-MGP-A01 and CB500F/CBR500R MGZ-A03). Frame checksums, upload checksums and calibration checksum fields are not interchangeable.</p>`,
      usedBy: ['Honda PGM-FI research profiles', 'Honda CB500F / CTX700 / CBR family'],
      workstation: ['Garage → transport K-Line', 'Tools → Honda offline decoder', 'Tools → Honda calibration checksum'],
      tags: ['honda', 'keihin', 'pgm-fi', 'kline', 'mgz', 'cbr', 'cb500'],
      related: ['topic-checksums-overview', 'protocol-kwp2000'],
    },
    {
      id: 'yamaha-dashboard',
      name: 'Yamaha dashboard K-Line stream',
      short: 'Listen-only 16,064-baud observation of the Yamaha MT-03 660 dashboard/ECU stream.',
      transport: 'K-Line, 12 V, via a Linux FTDI KKL adapter.',
      baud: '16,064 baud.',
      init: 'None — the stream runs on its own; the panel only listens.',
      addressing: 'Broadcast dashboard frames.',
      framing: 'Continuous stream, not request/response.',
      checksum: 'Not validated by this implementation.',
      body: `
<h3>Using it</h3>
<ol>
  <li>Disconnect any active ECU session.</li>
  <li>Attach the FTDI KKL adapter to the dashboard/ECU K-Line wire and enter its port.</li>
  <li>Tick the confirmation and press Observe for a two-second window.</li>
  <li>Read the candidate dashboard fields; nothing is transmitted to the bike.</li>
</ol>

<h3>Status</h3>
<p>The source reports testing on a 2010 MT-03 660; this integration has synthetic tests only. Yamaha R9 2026 CAN research lives in the separate broadcast-observation panel.</p>`,
      usedBy: ['Yamaha MT-03 660 (2010)'],
      workstation: ['Discovery → Yamaha K-Line observation'],
      tags: ['yamaha', 'mt-03', 'dashboard', 'kline', '16064', 'listen'],
      related: ['protocol-hdlan', 'protocol-kwp2000'],
    },
    {
      id: 'buell-ddfi',
      name: 'Buell DDFI TTL serial',
      short: 'A 5 V TTL serial link to Buell DDFI / DDFI-2 / DDFI-3 ECMs — not RS-232, not K-Line, not J1850.',
      transport: '5 V TTL serial (TX/RX/GND) through a Buell diagnostic cable or paired Bluetooth serial adapter.',
      baud: 'Set by the DDFI generation; the ECM identification step confirms it.',
      init: 'DDFI-specific serial handshake.',
      addressing: 'ECM-addressed serial commands.',
      framing: 'DDFI command/response packets.',
      checksum: 'DDFI packet checksum, validated per response.',
      body: `
<h3>Hardware warning</h3>
<p>TTL is not RS-232 and not K-Line. Feeding RS-232 levels into the ECM, or 12 V onto the TTL pin, destroys the interface. Verify adapter voltage, wiring, grounding, bike and ECM generation before connecting.</p>

<h3>What the panel does</h3>
<ul>
  <li><b>Identify</b> the ECM to confirm the DDFI generation.</li>
  <li><b>Live read</b> of the supported channels.</li>
  <li><b>Experimental fuel/spark EEPROM write</b> in its own collapsed panel, behind explicit confirmations and a verified backup. Source-derived maps also ship as XDF definitions, so you can inspect the EEPROM offline first.</li>
</ul>

<h3>Status</h3>
<p>Based on published DDFI research (ECMSpy lineage); synthetic-tested only. Treat every write as unrecoverable until you have proven your own recovery path on a spare ECM.</p>`,
      usedBy: ['Buell DDFI / DDFI-2 / DDFI-3'],
      workstation: ['Tools → Buell DDFI panel', 'Tools → Buell write panel', 'Firmware → Maps with a Buell XDF'],
      tags: ['buell', 'ddfi', 'ttl', 'serial', 'eeprom', 'ecmspy'],
      related: ['topic-howto-brand-workflows', 'ecu-buell'],
    },
    {
      id: 'rusefi-serial',
      name: 'rusEFI serial console and .ini definitions',
      short: 'Generic aftermarket engine controller access: a serial console, an INI definition for the unit, and page-based calibration read/write.',
      transport: 'USB/serial console (CDC ACM), 115,200 baud typically.',
      baud: 'Set by the controller’s console configuration.',
      init: 'Console handshake; the INI describes the protocol and pages.',
      addressing: 'Calibration pages addressed by index, with an output-channel stream alongside.',
      framing: 'Text command/response for the console; binary page transfer for calibration.',
      checksum: 'CRC per page/command where the firmware implements it.',
      body: `
<h3>Two things share this protocol</h3>
<ul>
  <li><b>rusEFI/TunerStudio .ini viewer</b> — parse a definition and see the constants, tables and output channels it declares, entirely offline.</li>
  <li><b>rusEFI aftermarket · live serial research</b> — connect to an explicitly selected rusEFI controller, read live channels and the calibration page list, and (behind its own gate) read or write a page.</li>
</ul>

<h3>Not for stock ECUs</h3>
<p>This is <b>not</b> a Harley Delphi, Power Vision or stock-ECU path. Selecting a rusEFI port while a stock ECU is on the other end can do nothing at best and confuse the controller at worst. Confirm the firmware banner before enabling writes.</p>

<h3>Building a tune</h3>
<p>The evidence-backed map builder can write a rusEFI-shaped calibration when the plan comes from an ini-defined table set. It still requires a checksum provider that matches the definition, and it still will not write without the gate.</p>`,
      usedBy: ['rusEFI aftermarket controllers'],
      workstation: ['Tools → rusEFI .ini viewer', 'Tools → rusEFI live read/write panel'],
      tags: ['rusefi', 'ini', 'tunerstudio', 'aftermarket', 'serial', 'page'],
      related: ['topic-checksums-overview', 'topic-howto-brand-workflows'],
    },
    {
      id: 'jetdrive',
      name: 'Dynojet JetDrive multicast telemetry',
      short: 'Dyno telemetry over local UDP multicast: AFR, RPM and torque channels from the dyno, not from the motorcycle ECU.',
      transport: 'UDP multicast on the local dyno network.',
      baud: 'N/A (packet network).',
      init: 'Join the multicast group and listen for a three-second window.',
      addressing: 'Channel-named samples keyed by dyno channel id.',
      framing: 'Datagram batches of timestamped channel samples.',
      checksum: 'No authentication or checksum — the data is trusted because you are on the dyno network.',
      body: `
<h3>What it is</h3>
<p>JetDrive publishes dyno measurements (wideband AFR, RPM, torque, operator channels) as multicast datagrams. The workstation listens for three seconds, groups samples by channel and reports counts and ranges — it never writes to the dyno.</p>

<h3>Hand-off to tuning</h3>
<p><b>Send capture to Map AFR Overlay</b> pivots the long-format samples into aligned wide frames (a <code>timestamp_ms</code> column plus one column per channel) and opens the offline AFR analyzer. From there you can pick the log column as the target AFR source, or set a constant or 2D XDF table target, and produce a bounded correction proposal.</p>

<h3>Honesty</h3>
<p>Dyno telemetry is not an ECU connection, not a tune writer and not an authenticated source. The integration is synthetic-tested only; channel names depend on the dyno’s configuration.</p>`,
      usedBy: ['Dynojet dyno with JetDrive-compatible software'],
      workstation: ['Tools → Dynojet JetDrive panel', 'Firmware → Maps → Offline AFR log overlay'],
      tags: ['jetdrive', 'dynojet', 'dyno', 'multicast', 'afr', 'udp', 'telemetry'],
      related: ['topic-howto-afr-jetdrive-tuning', 'topic-checksums-overview'],
    },
    {
      id: 'j2534',
      name: 'J2534 pass-thru interfaces',
      short: 'Vendor DLL based vehicle communication API: enumerated for discovery and supported sessions, never assumed to unlock flashing.',
      transport: 'Depends on the device (CAN, K-Line, J1850, ISO 9141).',
      baud: 'Configured by the pass-thru device per channel.',
      init: 'Pass-thru Connect/StartMsgFilter sequence through the vendor DLL.',
      addressing: 'Protocol-specific filters and message IDs.',
      framing: 'Device API messages.',
      checksum: 'Device/protocol dependent.',
      body: `
<h3>What the workstation does</h3>
<p>Firmware → <b>Adapter pre-flight</b> can enumerate installed J2534 devices and their supported protocols. That is interface discovery, not a calibration path: no bundled profile implements a J2534 flashing sequence, and none will be inferred from the mere presence of a DLL.</p>

<h3>Reality check</h3>
<ul>
  <li>A pass-thru device is a transport. The ECU’s programming sequence — session, security access, erase, transfer, checksum, reset — still has to be implemented and proven per family.</li>
  <li>Manufacturer software and subscriptions are separate from this project.</li>
  <li>Never start a flash on a battery that is not on a charger.</li>
</ul>`,
      usedBy: ['Any supported J2534 device (enumeration only)'],
      workstation: ['Firmware → Adapter pre-flight → J2534'],
      tags: ['j2534', 'pass-thru', 'dll', 'interface', 'can', 'flash'],
      related: ['protocol-can-iso-tp', 'topic-safety-gates'],
    },
    {
      id: 'security-access',
      name: 'SecurityAccess (seed / key)',
      short: 'The challenge-response step that unlocks protected ECU services: the ECU sends a seed, you return the correct key, and the session opens.',
      transport: 'Any of the above — the security exchange travels inside the diagnostic protocol.',
      baud: 'Same as the session.',
      init: 'After the diagnostic session is opened, request the seed and answer with the key.',
      addressing: 'Service 0x27 (SecurityAccess) or the family’s equivalent.',
      framing: 'Seed request → seed bytes → key request with the computed key → positive/negative response.',
      checksum: 'Inside the enclosing frame checksum.',
      body: `
<h3>Why it matters</h3>
<p>Reading live data rarely needs a key. Reading or writing calibration usually does. A wrong key is not harmless: many ECUs rate-limit or lock the service after repeated failures, which can require a power cycle, a timeout, or a bench recovery.</p>

<h3>How this program handles keys</h3>
<ul>
  <li><b>No verified key algorithm ships for any Guzzi ECU.</b> The SecurityAccess panel says so rather than pretending.</li>
  <li>You supply a trusted provider plugin (algorithms you have the right to use). It is executed in an isolated worker with a timeout, memory and filesystem limits, and its file hash is rechecked immediately before use.</li>
  <li>An unverified provider can be armed for one session behind an explicit acknowledgement; the session log records the decision, the provider id and the seed.</li>
  <li>The 5AM writer uses the documented <code>5am_util</code> key sequence; it is simulator-tested and gated separately from the calibration checksum.</li>
</ul>

<h3>Never do this</h3>
<p>Do not brute-force seeds on a customer bike, and do not reuse another ECU’s key without confirming the algorithm. The seed is usually a random number — a “key” that worked once is proof of nothing.</p>`,
      usedBy: ['IAW 5AM (documented 5am_util sequence)', 'Any profile with a security plugin'],
      workstation: ['Firmware → SecurityAccess key providers', 'Firmware → Write → preconditions'],
      tags: ['securityaccess', 'seed', 'key', '0x27', 'unlock', 'plugin', '5am'],
      related: ['topic-safety-gates', 'topic-write-path'],
    },
  ];

  window.GOB_HELP.protocols = PROTOCOLS;
}());

/* ======================================================================
 * TOPICS — guides, overviews, reference articles and the glossary.
 * Rendered at #help/<id>. `body` is trusted HTML authored here.
 * ==================================================================== */
(function () {
  'use strict';

  const TOPICS = [
    /* --------------------------------------------------- START HERE */
    {
      id: 'getting-started', title: 'Start here: the 10-minute tour of GuzziOnBoard', category: 'howto',
      summary: 'What this program is, the five perspectives, the one rule that keeps you out of trouble, and the shortest safe path from a cold laptop to a logged, understood motorcycle.',
      tags: ['start', 'intro', 'tour', 'overview', 'first run', 'perspectives', 'help'],
      related: ['howto-first-connection', 'howto-backup-basemap', 'safety-gates'],
      tools: [{ label: 'Open the Garage', view: 'garage' }, { label: 'Open the Help center', view: 'help' }],
      body: `
<h3>What GuzziOnBoard is</h3>
<p>A motorcycle diagnostics, calibration-research and workshop workstation. It talks to an ECU through a real adapter, or to a built-in simulator that needs no hardware at all. It reads live data, fault codes and memory; it renders calibration maps with TunerPro XDF definitions; it builds evidence-backed tunes; and it gates every write behind preconditions you can read.</p>
<p>Coverage is deliberately uneven and the program says so everywhere: a family may have verified live data but no memory path, or a memory reader but no write path. <b>Capability is per family, not per brand.</b></p>

<h3>The five perspectives</h3>
<table class="help-table"><thead><tr><th>Perspective</th><th>What lives there</th></tr></thead><tbody>
<tr><td><b>01 Setup &amp; Link</b></td><td>Garage (bike, transport, adapter, checklist), Overview (identity, capabilities), Equipment guide.</td></tr>
<tr><td><b>02 Gauge Dash</b></td><td>Live data with timeline and findings, Sessions with replay and compare, the simulated bike.</td></tr>
<tr><td><b>03 XDF &amp; ROM</b></td><td>The whole ECU memory pipeline: adapter pre-flight, backup, base map, validate, maps, write, security.</td></tr>
<tr><td><b>04 DTC &amp; I/O</b></td><td>Fault codes, guided tests, service actions (actuators and resets).</td></tr>
<tr><td><b>05 Bench &amp; Logs</b></td><td>The tools bench (offline research and workshop maths), Discovery, and the service report.</td></tr>
</tbody></table>
<p>A sixth section, <b>06 Help &amp; Reference</b>, is this knowledge base. <kbd>Ctrl</kbd>+<kbd>K</kbd> searches all of it, plus every tool, panel, menu command, ECU and XDF in the program.</p>

<h3>The one rule</h3>
<div class="gate-card warn"><h4>Read before you write — and keep a way back</h4><p>No write happens without a verified backup, a vaulted base map re-hashed at the moment of writing, a hardware-family match and a single-use confirmation token. The program will refuse, loudly, and record the refusal in the session log. That refusal is a feature.</p></div>

<h3>Shortest safe path</h3>
<ol>
  <li><b>Garage</b> → pick make/model/year, transport <i>Simulator</i> for practice, work the checklist, Connect.</li>
  <li><b>Overview</b> → Identify ECU, read What this ECU supports.</li>
  <li><b>Live data</b> → poll, pick channels, read the findings and the raw bytes.</li>
  <li><b>ECU memory</b> → adapter pre-flight, Backup (dual read), confirm the base map is vaulted.</li>
  <li><b>Maps &amp; tables</b> → render with an XDF, change one cell, review the diff.</li>
  <li><b>Build</b> → produce a tune, validate it, then read the write gate before touching a real ECU.</li>
</ol>
<p>Then read <a href="#help/howto-first-connection">Connect, identify &amp; log</a> for the real-hardware version of that path, and <a href="#help/safety-gates">Safety gates</a> before the first write.</p>`,
    },
    {
      id: 'howto-first-connection', title: 'How-to: connect, identify and log live data', category: 'howto',
      summary: 'From cable to CSV in eleven steps, with the exact panels, the init-method decision, and how to tell a good link from a lucky one.',
      tags: ['connect', 'identify', 'live', 'log', 'adapter', 'kline', 'can', 'first'],
      related: ['topic-protocols-overview', 'howto-backup-basemap', 'safety-troubleshooting'],
      tools: [
        { label: 'Garage & link', view: 'garage', selector: '#connectionPanel' },
        { label: 'Overview / identity', view: 'overview', selector: '#identityPanel' },
        { label: 'Live data', view: 'live' },
      ],
      body: `
<h3>Before you plug anything in</h3>
<ol>
  <li>Note the <b>exact</b> model, year and ECU label. Catalog entries can overlap within a model year, and a research entry is not a fitment claim.</li>
  <li>Match the interface to the protocol: KKL/FTDI for K-Line, SLCAN/SocketCAN/PCAN for CAN, ELM327 (VPW) for J1850 Harleys, TTL serial for Buell, rusEFI console for aftermarket. See the <a href="#help/tool-view-equipment">Equipment guide</a>.</li>
  <li>Ignition key handling differs by ECU: some need key-on/engine-off, some need the engine running for live data. The checklist in the Garage states what this profile needs.</li>
  <li>Put the bike on a stable surface, in neutral, and know where the kill switch is.</li>
</ol>

<h3>Select the vehicle</h3>
<ol>
  <li>Open <b>Garage</b> → <b>1 · Motorcycle</b>. Choose make, model and year; the coverage line shows how many ECU profiles and model variants matched.</li>
  <li>If two ECU fitments exist for the year, use the <b>ECU override</b> dropdown — the choice is validated against the catalog and refused if it is not cataloged for that make/model/year.</li>
</ol>

<h3>Select the connection</h3>
<ol start="3">
  <li><b>2 · Connection</b> → transport. Choose <i>Simulator</i> for a first run: nothing is transmitted.</li>
  <li>Enter the serial device (<code>/dev/ttyUSB0</code>, <code>COM3</code>) or CAN channel (<code>can0</code>) and, for CAN, the interface type.</li>
  <li><b>Init method</b>: leave it on profile default unless you have a reason. If fast init fails and the family is 5-baud-only, switch to <i>5-baud</i>; automatic tries fast and then slow with the standard idle times and reports each attempt on the Link card.</li>
  <li>Work down the checklist. Mandatory rows must be acknowledged; Connect stays disabled until they are.</li>
  <li>Press <b>Connect</b>. The status bar and connection card turn green; the Link card reports the negotiated protocol, baud rate, addresses and timings.</li>
</ol>

<h3>Identify</h3>
<ol start="8">
  <li>Open <b>Overview</b>. Identification is mandatory before any command.</li>
  <li>Press <b>Identify ECU</b>. Read the part/hardware/software fields and the raw response. If the part number disagrees with the label on the ECU, stop and re-check the vehicle selection.</li>
  <li>Read <b>What this ECU supports</b>. Anything grey is not implemented for this family; the reason is printed. Do not look for a hidden toggle.</li>
</ol>

<h3>Log</h3>
<ol start="11">
  <li>Open <b>Live data</b> and press <b>Start polling</b>. Tick the channels you need; the timeline gives each one its own scale and marks gaps.</li>
  <li>Watch <b>Plausibility checks</b> — they name the numbers they react to. They are opinions, never a diagnosis.</li>
  <li>Press <b>Export Live CSV</b> to write the current session’s samples, or use <b>File → Export Live Telemetry</b>.</li>
</ol>

<h3>How to tell the link is good</h3>
<ul>
  <li>Every frame passes its checksum and the Link card names the negotiated protocol rather than “K-Line”.</li>
  <li>Live values move the way the bike moves, and the raw bytes behind each value are stable.</li>
  <li>No retries or timeouts accumulate in the session events.</li>
</ul>
<p>If not, jump to <a href="#help/safety-troubleshooting">Troubleshooting</a> before changing anything.</p>`,
    },
    {
      id: 'howto-setup-desktop', title: 'How-to: install, run, drives, presets and shortcuts', category: 'howto',
      summary: 'Install the Python package or desktop build, set up the adapter driver and latency timer, configure save/load presets, and learn the keyboard shortcuts.',
      tags: ['install', 'setup', 'desktop', 'driver', 'ftdi', 'latency', 'presets', 'shortcuts', 'preferences'],
      related: ['howto-first-connection', 'topic-tools-keyboard-shortcuts'],
      tools: [
        { label: 'Preferences', view: 'garage', selector: '#openPreferencesBtn' },
        { label: 'Adapter pre-flight', view: 'firmware', selector: '#adapterPanel' },
      ],
      body: `
<h3>Run it</h3>
<ul>
  <li><code>pip install -e .</code> then <code>guzzionboard</code> — opens the workstation at <code>http://127.0.0.1:8000</code> (loopback only, by design).</li>
  <li><code>guzzionboard --desktop</code> — a native window with the desktop bridge (file dialogs, printing, folder opening).</li>
  <li><code>guzzionboard --selftest</code> — checks the catalog, UI, API and checksum worker, then exits.</li>
  <li>Real hardware needs the optional extra: <code>pip install -e '.[hardware]'</code> for pyserial and python-can.</li>
</ul>

<h3>Adapter setup</h3>
<ol>
  <li>Install the interface driver. For FTDI KKL cables use the mirrored WHQL CDM bundle offered by the adapter pre-flight card if Windows shows no COM port.</li>
  <li>Set the FTDI <b>latency timer to 1 ms</b>. The default 16 ms turns a 20-minute read into hours, and it is the most common cause of a “slow” or failing memory read.</li>
  <li>Run <b>ECU memory → 1 · Adapter pre-flight</b>: check the port, measure round-trip latency, enumerate J2534 devices if you use one.</li>
  <li>For SocketCAN, configure the interface yourself: <code>ip link set can0 up type can bitrate 500000</code>.</li>
</ol>

<h3>Preferences and presets</h3>
<ol>
  <li><kbd>Ctrl</kbd>+<kbd>,</kbd> opens Preferences: theme, density, temperature unit, poll cadence, default connection mode, exit confirmation.</li>
  <li><b>Save presets</b> are where reports and exports land. <b>Load presets</b> are where images, base maps and XDFs are found.</li>
  <li>Add a preset with a name, path and note. Activate one from the menu-bar chip or Quick Settings; the active preset shows in the menubar and status bar.</li>
  <li><b>File → Browse Load Preset Folder…</b> browses a preset and inserts the chosen path into the field that asked for it.</li>
  <li>Export Preferences (.json) for a backup; Import restores; Reset to Defaults starts clean.</li>
</ol>

<h3>Appearance and units</h3>
<p>Quick Settings changes theme (Dark, Light, Auto), density (Comfortable, Compact), temperature unit and poll cadence without opening the modal. Celsius is what the ECU sends; Fahrenheit is display-only conversion.</p>

<h3>Shortcuts</h3>
<p>See <a href="#help/topic-tools-keyboard-shortcuts">Keyboard shortcuts</a> for the full table — including <kbd>Ctrl</kbd>+<kbd>K</kbd> global search, <kbd>F1</kbd> help, <kbd>Ctrl</kbd>+<kbd>B</kbd> explorer dock and <kbd>Ctrl</kbd>+<kbd>P</kbd> print.</p>`,
    },

    /* --------------------------------------------------- BACKUP */
    {
      id: 'howto-backup-basemap', title: 'How-to: verified backup, attestation and base map', category: 'howto',
      summary: 'Produce a dual-read backup that is actually a backup, vault the untouched base map, and attest an external full dump when you already have one.',
      tags: ['backup', 'base map', 'attest', 'dual read', '5am', 'guzzidiag', 'vault', 'sha256'],
      related: ['topic-write-path', 'topic-safety-recovery', 'topic-checksums-validate'],
      tools: [
        { label: 'Backup panel', view: 'firmware', selector: '#backupPanel' },
        { label: 'Base map vault', view: 'firmware', selector: '#baseMapPanel' },
        { label: 'Compare images', view: 'firmware', selector: '#memoryComparePanel' },
      ],
      body: `
<h3>Why two reads</h3>
<p>One read over a noisy K-Line is not a backup: a dropped byte produces a plausible-looking file that is wrong everywhere after the gap. The workstation reads the whole region twice and keeps the file <b>only if both reads agree byte for byte</b>. Any disagreement aborts the operation and keeps nothing.</p>

<h3>Read the ECU</h3>
<ol>
  <li>Connect, identify the ECU, then open <b>ECU memory → 2 · Backup</b>.</li>
  <li>Choose the region. On the IAW 5AM the flash region is <code>0x4000</code>–<code>0x50000</code>: 311,296 bytes (304 KiB), read as 19 blocks. EEPROM reads are offered where the profile declares them.</li>
  <li>Press <b>Backup</b>. Expect roughly 20 minutes on a 10,400-baud K-Line link — a 1 ms latency timer is what keeps that estimate honest.</li>
  <li>Watch the block progress. A skipped block is reported explicitly (<i>attempt_5am_skipped_blocks</i>) and never silently filled.</li>
  <li>On success you get a hash, a size/hardware description, a validation summary and a vaulted base map.</li>
</ol>

<h3>Confirm the base map</h3>
<ol start="6">
  <li>Open <b>2b · Base map</b>. The card shows the vaulted image, its SHA-256 and when it was filed.</li>
  <li>The hash is re-checked every time a write is considered. If the file changed on disk, the write gate refuses.</li>
  <li>Use <b>Restore</b> to stage the vaulted image as the recovery target; use <b>Export</b> to keep a copy outside the app.</li>
</ol>

<h3>Attesting an external backup</h3>
<ol start="9">
  <li>If you already have a verified full dump from GuzziDiag, IAW5xReader or a bench reader, expand <b>Attest external verified full backup</b>.</li>
  <li>Choose the file. Both a <b>304 KiB</b> (311,296 B) flash image and a <b>320 KiB</b> (327,680 B) full dump are accepted; for the latter the <code>0x4000</code> bootloader prefix is sliced off and reported (<i>sliced_from_full_dump</i>).</li>
  <li>Read the result: path, byte count, SHA-256, describe/validation output and the base-map status it produced.</li>
  <li>Tick the statement of fact — verbatim: <code>I confirm this file is a verified full backup from this exact ECU</code> — and press Attest.</li>
</ol>

<div class="gate-card warn"><h4>Attestation is a claim, not a proof</h4><p>The program cannot verify that a file came from this ECU. It verifies structure, size, checksums and hardware strings, then records <i>your</i> statement alongside the file hash. Be certain: a wrong base map is worse than no base map, because it looks like a way back.</p></div>

<h3>Verify repeatability</h3>
<p>Compare the new backup with the previous one under <b>Compare two ECU image files</b>. Identical bytes prove repeatability; they do not prove completeness or that the layout applies. Keep the original image forever — SD cards and laptops fail more often than ECUs.</p>`,
    },

    /* --------------------------------------------------- XDF EDITING */
    {
      id: 'howto-xdf-editing', title: 'How-to: render and edit XDF tables, constants, flags and patches', category: 'howto',
      summary: 'Load an XDF against a dump, navigate 260-table definitions, edit cells and constants safely, toggle bit flags, apply binary patches, and review the diff before building.',
      tags: ['xdf', 'maps', 'tables', 'constants', 'flags', 'patches', 'float', 'diff', 'edit', 'tunerpro'],
      related: ['topic-checksums-xdf-math', 'howto-custom-build-and-flash', 'topic-ecus-memory-geometry'],
      tools: [
        { label: 'Maps & tables', view: 'firmware', selector: '#mapsCard' },
        { label: 'Offline AFR overlay', view: 'firmware', selector: '.map-log-tools' },
      ],
      body: `
<h3>Load</h3>
<ol>
  <li>Open <b>ECU memory → Maps &amp; tables</b>.</li>
  <li>Choose the image (a backup, a base map, or any local file) and an <b>XDF</b>. The bundled library is grouped by bike and family; drop your own <code>.xdf</code> files into <code>~/.guzzionboard/xdfs/</code> to add them.</li>
  <li>Leave <b>Only definitions that fit</b> ticked unless you are researching. Uncatalogued XDFs are refused by the build fitment check even if they render.</li>
  <li>Press <b>Render</b>. The explorer dock lists every table, constant, flag and patch — the category groups (constants, flags, patches) stay pinned above the tables so a 260-table definition never hides them.</li>
</ol>

<h3>Edit a table</h3>
<ol start="5">
  <li>Click a cell, type the new engineering value, press <kbd>Enter</kbd>. The cell stages a change with its <b>expected raw value</b> — an optimistic lock.</li>
  <li>Rows and columns can be scaled, smoothed or copied where the XDF supports it. Axis editing follows the same expected-value rule.</li>
  <li>Use undo/redo freely; nothing reaches the image until you build.</li>
</ol>

<h3>Constants, flags and patches</h3>
<ul>
  <li><b>Constants</b> are single scalars (idle speed, rev limit, injector size). Same click-to-edit flow.</li>
  <li><b>Flags &amp; Switches</b> read a bit mask at an address. Toggling writes the mask while preserving every sibling bit — the panel shows the raw byte before and after.</li>
  <li><b>Binary patches</b> are fixed hex spans with a state: <i>applied</i>, <i>unapplied</i> or <i>mismatch</i>. Apply/revert is allowed only when the current bytes match the patch’s expected base data; a mismatch requires an explicit confirmation and is recorded.</li>
  <li>Float maps and scalars (IEEE-754 32/64-bit) display as real numbers; the raw hex is beside them.</li>
</ul>

<h3>Review before you build</h3>
<ol start="9">
  <li>Open the <b>diff</b>: it lists every changed byte range with before/after values, grouped by table/constant/flag/patch.</li>
  <li>Check the counts. A “one cell” edit that produced forty byte changes means the map is wrong or you edited a mis-scaled table.</li>
  <li>Export the project (.json) if you want to keep the edit set independently of the image.</li>
</ol>

<div class="gate-card warn"><h4>Definitions are third-party research</h4><p>Bundled XDFs come from the GuzziDiag/IAWDiag community and source-derived research. Their titles and scalings can be wrong for your exact software version. Validate against a known value (a stock idle speed, a rev limit you can observe) before trusting an edit.</p></div>`,
    },

    /* --------------------------------------------------- AFR / DYNO */
    {
      id: 'howto-afr-jetdrive-tuning', title: 'How-to: wideband AFR analysis and the JetDrive dyno overlay', category: 'howto',
      summary: 'Turn a wideband log — or a live dyno capture — into bounded, reviewable fuel-correction proposals, with channel, constant or 2D XDF-table targets.',
      tags: ['afr', 'wideband', 'lambda', 'dyno', 'jetdrive', 'log', 'fuel', 've', 'correction', 'csv'],
      related: ['howto-custom-build-and-flash', 'topic-checksums-overview', 'protocol-jetdrive'],
      tools: [
        { label: 'AFR overlay', view: 'firmware', selector: '.map-log-tools' },
        { label: 'JetDrive capture', view: 'tools', selector: '#jetdrivePanel' },
      ],
      body: `
<h3>The idea</h3>
<p>Measure what the engine actually did (wideband AFR in the same cells you are tuning), compare it to a target, and let the workstation propose a <b>bounded</b> multiplicative correction per cell. It never writes; it produces a proposal you review, then build.</p>

<h3>Prepare the log</h3>
<ol>
  <li>Export a CSV with at least RPM, load (TPS/MAP) and measured AFR. Three columns are enough; extra channels are kept.</li>
  <li>Make sure the header names are stable and the unit is AFR, not lambda. <b>No lambda conversion is performed</b> — convert it in your logger.</li>
  <li>Open <b>Maps &amp; tables → Offline AFR log overlay</b> and choose the CSV, or use <b>File → Load Telemetry / AFR Log</b>.</li>
</ol>

<h3>Pick the target AFR source</h3>
<ul>
  <li><b>Log column</b> — the target is a column in the same CSV (common when your logger carries a target channel).</li>
  <li><b>Constant</b> — one AFR for the whole pull (9.0–22.0). Fast, honest, coarse.</li>
  <li><b>XDF table</b> — pick a rendered 2D table (for example a target-AFR-by-load-and-RPM table). Values are bilinearly interpolated at the cell’s coordinates, so an axis-misaligned table still gives a sensible target.</li>
</ul>

<h3>Map the axes</h3>
<ol start="4">
  <li>Select the XDF table you want to correct (fuel/VE/trim).</li>
  <li>Map the log columns to the table’s row and column axes; the analyzer bins samples into cells, with a delay alignment so a slow sensor does not smear the result.</li>
  <li>Set the minimum samples per cell and the maximum correction per pass. Both are your safety rails.</li>
</ol>

<h3>Run and read</h3>
<ol start="7">
  <li>Press <b>Analyze</b>. You get per-cell measured AFR, target, error, sample count and a proposed correction, plus cells it refused for lack of data.</li>
  <li>Read the summary: how many cells moved, the largest correction, and which cells were extrapolated.</li>
  <li>Stage the proposal into the map editor, review the diff, and continue in <a href="#help/howto-custom-build-and-flash">Build &amp; write</a>.</li>
</ol>

<h3>The dyno shortcut</h3>
<ol start="10">
  <li>In <b>Tools → Dynojet JetDrive</b>, confirm you are on the dyno network and press <b>Capture</b> (three seconds of multicast).</li>
  <li>Review channel counts and ranges.</li>
  <li>Press <b>Send capture to Map AFR Overlay</b>. The long-format samples are pivoted into aligned wide frames (<code>timestamp_ms</code> + one column per channel) and the overlay opens with them loaded.</li>
</ol>

<div class="gate-card warn"><h4>What this is not</h4><p>Not a dyno operator, not an autotune that writes, and not a certification of AFR. Sensor placement, exhaust leaks, misfires and closed-loop interference all corrupt wideband data. A correction that looks perfect in one pull can be wrong at another temperature.</p></div>`,
    },

    /* --------------------------------------------------- BUILD & WRITE */
    {
      id: 'howto-custom-build-and-flash', title: 'How-to: build a custom tune and run the gated write', category: 'howto',
      summary: 'Author a tune from operator judgement, a dyno session or a wideband log; lock the plan, verify the checksum, then walk the write gate row by row.',
      tags: ['build', 'tune', 'write', 'flash', 'gate', 'checksum', 'dyno', 'operator', 'provenance', 'token'],
      related: ['topic-write-path', 'topic-safety-gates', 'topic-checksums-plugins', 'howto-xdf-editing'],
      tools: [
        { label: 'Map builder', view: 'firmware', selector: '#mapBuilder' },
        { label: 'Validate image', view: 'firmware', selector: '#validatePanel' },
        { label: 'Write gate', view: 'firmware', selector: '#writePanel' },
      ],
      body: `
<h3>1. Start from a real image</h3>
<ol>
  <li>Load the base map (or the verified backup) and the correct XDF, then render.</li>
  <li>Edit tables, constants, flags or patches — or stage an AFR proposal — until the diff says what you intend.</li>
</ol>

<h3>2. Record the provenance</h3>
<p>The builder refuses to produce a tune without a provenance record. Pick the mode that describes where the numbers came from:</p>
<table class="help-table"><thead><tr><th>Mode</th><th>Use it when</th><th>URL</th></tr></thead><tbody>
<tr><td><b>operator</b></td><td>You made the decisions from workshop judgement, a manual or a known-good calibration.</td><td>optional</td></tr>
<tr><td><b>dyno</b></td><td>The changes come from measured pulls on a dyno.</td><td>optional</td></tr>
<tr><td><b>afr-log</b></td><td>The changes come from a wideband log analyzed in the overlay.</td><td>optional</td></tr>
<tr><td><b>external</b></td><td>You are staging a published/community package.</td><td><b>required</b>, http(s)</td></tr>
</tbody></table>
<p>Custom modes require a title (≥ 3 characters) and a rationale (≥ 10 characters). The result is labelled <code>&lt;mode&gt;-authored-not-endorsed</code>: the program records who said what, and endorses nothing.</p>
<ol start="3">
  <li>Fill in <b>title</b>, <b>rationale</b> and, if you have one, a reference URL.</li>
  <li>Tick the responsibility acknowledgement, verbatim: <code>I understand modified maps can damage the engine and accept responsibility</code>.</li>
</ol>

<h3>3. Checksum and plan lock</h3>
<ol start="5">
  <li>If the rendered XDF declares a calibration checksum, select an explicit <b>provider</b>. Providers are never auto-selected, and a provider must support every declared checksum title.</li>
  <li>Preview. Preview and build preserve image length, refuse more than 4096 changed bytes, and record provider id/version, plugin hash, isolation mode, input/output hashes and every changed range.</li>
  <li>The plan is locked to a SHA-256 of the input plus the change set. If either changes, the lock no longer matches and the write gate refuses.</li>
</ol>

<h3>4. Validate the built image</h3>
<ol start="8">
  <li>Open <b>3 · Validate an image</b> and validate the built file.</li>
  <li>Size, vector table, entropy and hardware family are checked. <b>An HW1xx image never goes into an HW3xx ECU</b> — there is no override for that.</li>
</ol>

<h3>5. Walk the write gate</h3>
<ol start="10">
  <li>Open <b>4 · Write</b>. Every row is a precondition with its own reason string. Nothing is hidden behind “advanced”.</li>
  <li>Turn on programming for this session (it is opt-in and time-limited) with the acknowledgement <code>I have a verified backup and accept the risk</code>.</li>
  <li>If the family has an implemented writer that is not bench-verified (for example the IAW 5AM KWP2000 writer), unlock it explicitly with <code>I have an external recovery plan and accept unverified ECU write risk</code>. Unlocking a writer raises the effective capability for this session <b>only</b>; it does not touch the catalog on disk.</li>
  <li>Build a confirmation token and verify it. Tokens are single-use; any material change invalidates them.</li>
  <li>Press <b>Write</b>. The session is held exclusively: enter programming session, security access, transfer block by block, then read back and compare.</li>
  <li>Afterwards, re-read the region and compare it to the image you sent. A write that is not read back is not verified.</li>
</ol>

<div class="gate-card warn"><h4>Prepare the recovery before the write</h4><p>Battery on a charger, laptop on mains, adapter cable strain-relieved, the verified backup in the vault <i>and</i> on another disk, and a written recovery plan (second ECU, bench harness, trailer). Unverified writers exist in this program because you asked for them — they are not a warranty.</p></div>`,
    },

    /* --------------------------------------------------- BRAND WORKFLOWS */
    {
      id: 'howto-brand-workflows', title: 'How-to: Harley, Buell, Honda, rusEFI and Power Vision workflows', category: 'howto',
      summary: 'Which panel to use for each brand path, what each one can actually do, and where the research boundary sits.',
      tags: ['harley', 'buell', 'honda', 'rusefi', 'power vision', 'delphi', 'brand', 'workflow'],
      related: ['topic-ecu-harley-family', 'topic-ecu-honda', 'topic-ecu-buell', 'protocol-buell-ddfi'],
      tools: [
        { label: 'Harley region workspace', view: 'tools', selector: '#harleyRegion' },
        { label: 'Power Vision editor', view: 'tools', selector: '#pvvEditor' },
        { label: 'Buell DDFI', view: 'tools', selector: '#buellDdfi' },
        { label: 'rusEFI panel', view: 'tools', selector: '#rusefiTunePanel' },
      ],
      body: `
<h3>Harley-Davidson Delphi</h3>
<ol>
  <li><b>Garage</b>: choose the model/year. Delphi CAN identity profiles use 500 kbit/s and 0x7E0/0x7E8; older bikes use J1850 VPW through an ELM327 that explicitly supports VPW.</li>
  <li><b>Identity/DTC/live</b>: research-grade. Delphi CAN live mapping is source-derived; treat values as candidates.</li>
  <li><b>Offline calibration region workspace</b> (Tools): inspect a 160 KiB calibration or 16 KiB tune, compare regions, export the 16 KiB region.</li>
  <li><b>Centurion header research</b>: compare candidate header fields across up to two files.</li>
  <li><b>Power Vision PVV editor</b>: inspect a PVV XML, edit cells, save a new XML copy. No device connection.</li>
  <li><b>Experimental Delphi CAN memory</b> (Tools) can read a calibration and has a 16 KiB tune write panel. A read downloads an authentication payload to ECU address zero — it can alter ECU state. Synthetic-tested only.</li>
</ol>

<h3>Buell DDFI</h3>
<ol>
  <li>Use a <b>5 V TTL</b> Buell cable or paired Bluetooth serial adapter — never RS-232, K-Line or J1850.</li>
  <li>Identify the ECM to confirm DDFI/DDFI-2/DDFI-3, then read live data.</li>
  <li>Inspect the EEPROM offline with the bundled Buell XDFs before considering the experimental fuel/spark write.</li>
</ol>

<h3>Honda</h3>
<ol>
  <li>Live: K-Line PGM-FI profiles (research scope). Several Honda catalog entries have no wire definition and refuse physical sessions.</li>
  <li>Offline: paste complete frames into the <b>Honda K-Line offline decoder</b>; bad checksums are refused.</li>
  <li>Calibration: the <b>Honda source-ID checksum</b> tool and the two bundled providers are locked to specific XDFs and source-image hashes.</li>
</ol>

<h3>rusEFI (aftermarket)</h3>
<ol>
  <li>View a <b>.ini</b> definition to see its constants, tables and channels.</li>
  <li>Connect the rusEFI serial console through the live panel; read channels and pages.</li>
  <li>Its tune read/write has its own gate. Not for stock Delphi ECUs and not a Power Vision substitute.</li>
</ol>

<h3>Dynojet JetDrive</h3>
<p>Dyno telemetry only: capture three seconds of multicast and hand it to the AFR overlay. It never talks to the motorcycle ECU.</p>

<h3>Kawasaki, Suzuki, Triumph, Yamaha</h3>
<p>Research-grade live or raw-snapshot profiles, offline decoders, and clearly-labelled checksum research. See <a href="#help/topic-ecu-suzuki-kawasaki">Suzuki &amp; Kawasaki</a> and <a href="#help/topic-ecu-triumph-other">Triumph, Yamaha and others</a>.</p>`,
    },

    /* --------------------------------------------------- DIAGNOSTICS */
    {
      id: 'howto-guided-diagnostics', title: 'How-to: fault codes, guided tests and service actions', category: 'howto',
      summary: 'Read and clear DTCs safely, run a guided test that returns a verdict, and pulse actuators or reset adaptations without leaving something energised.',
      tags: ['dtc', 'faults', 'guided', 'procedure', 'actuator', 'reset', 'clear', 'diagnostics'],
      related: ['topic-protocols-overview', 'safety-gates'],
      tools: [
        { label: 'Fault codes', view: 'faults' },
        { label: 'Guided tests', view: 'procedures' },
        { label: 'Service actions', view: 'service' },
      ],
      body: `
<h3>Read faults</h3>
<ol>
  <li>Connect and identify the ECU.</li>
  <li>Open <b>Fault codes</b> and press <b>Read DTCs</b>. Stored and current codes are listed with the raw payload and any description the profile supports.</li>
  <li>Write the codes down (or build a report) <b>before</b> clearing: the light may not come back for days.</li>
</ol>

<h3>Clear faults</h3>
<ol start="4">
  <li><b>Clear DTCs</b> is gated: engine state, ignition state and a confirmation are required.</li>
  <li>Clearing also clears freeze-frame and readiness data. On an emissions-controlled bike that can matter legally — check local rules.</li>
  <li>The clear is recorded as a safety decision in the session log.</li>
</ol>

<h3>Run a guided test</h3>
<ol start="7">
  <li>Open <b>Guided tests</b>. Available tests are those the profile implements; unavailable ones list the missing capabilities.</li>
  <li>Read the preconditions and the channel list before starting.</li>
  <li>Press the test, follow the prompt, then read the verdict with the thresholds it used. Observations are ordinary live reads, so nothing about the verdict is hidden.</li>
  <li>Anything that actuates appears in the session events with its start and end.</li>
</ol>

<h3>Actuators and resets</h3>
<ol start="11">
  <li>Open <b>Service actions</b>. Each action shows its precondition card; the button stays disabled until the state matches.</li>
  <li>Pulse an actuator for the offered window. IAW ECUs have <b>no output timer</b> — the workstation owns the deadline and releases on expiry, on disconnect and if the browser goes away.</li>
  <li>Adaptation/learning resets discard learned values permanently. Confirm the engine state and battery voltage first.</li>
</ol>

<div class="gate-card warn"><h4>The bike is live</h4><p>Injectors squirt fuel, coils make sparks and the fuel pump pressurises the rail. Neutral, secure, ventilated, no loose fuel lines, and never with anyone’s hands in the throttle bodies.</p></div>`,
    },

    /* --------------------------------------------------- SESSIONS & REPORTS */
    {
      id: 'howto-sessions-and-reports', title: 'How-to: record, replay, compare and report a session', category: 'howto',
      summary: 'Where sessions are stored, how replay recomputes derived values, how to compare two sessions honestly, and how to produce a shareable service report.',
      tags: ['sessions', 'record', 'replay', 'compare', 'report', 'export', 'print', 'pdf'],
      related: ['howto-first-connection', 'safety-gates'],
      tools: [
        { label: 'Sessions', view: 'sessions' },
        { label: 'Report', view: 'report' },
      ],
      body: `
<h3>Recording</h3>
<p>Every connection, read, refusal, acknowledgement and write is appended to a session log under <code>~/.guzzionboard/sessions</code>. Start the workstation with <code>--no-record</code> to disable logging for that run.</p>

<h3>Replay</h3>
<ol>
  <li>Open <b>Sessions</b> and pick a recording.</li>
  <li>Read the <b>Events</b> timeline first: it is the audit trail, including what was refused and why.</li>
  <li>Scrub the replay. Derived values and plausibility findings are recomputed from the recorded bytes — not re-read from the ECU.</li>
</ol>

<h3>Compare two sessions</h3>
<ol start="4">
  <li>Select session A and B under <b>Compare two sessions</b>.</li>
  <li>The comparison names channels whose means moved, with the sample counts behind them.</li>
  <li>Sessions are not time-aligned, so this is a statistical comparison, not an overlay. For time alignment use a CSV export and your own tooling.</li>
</ol>

<h3>Report</h3>
<ol start="7">
  <li>Open <b>Report</b>, press <b>Build report</b>.</li>
  <li>Download .txt or .json, or print/save as PDF (<kbd>Ctrl</kbd>+<kbd>P</kbd>).</li>
  <li>With a save preset active, <b>File → Save Report to Active Save Preset</b> writes it into that folder and the status bar shows which preset was used.</li>
  <li>Redact customer details before sharing: reports contain part numbers, VIN-adjacent identifiers and timestamps.</li>
</ol>`,
    },

    /* --------------------------------------------------- TOOLS topics */
    {
      id: 'tools-directory', title: 'Every tool & workspace, explained (generated directory)', category: 'tools',
      summary: 'One entry per view, panel, dialog and workshop utility, with what it does, how to use it and a jump button into the live program.',
      tags: ['tools', 'directory', 'index', 'all tools', 'panels', 'views'],
      related: ['tools-search-and-links', 'topic-tools-keyboard-shortcuts'],
      tools: [{ label: 'Open the tools bench', view: 'tools' }],
      body: `
<p>Every tool is filed under its manufacturer — or under <b>General</b> when it works on any motorcycle (or needs no bike at all). The same grouping drives the Brand dropdown on the Tools bench; the brand picker below narrows this page.</p>
<p>This directory is generated from the same data the search box uses, so a tool that is missing here is missing from search too — report it as a bug.</p>
<div id="helpToolDirectory" class="help-tool-directory"><p class="muted">Loading tool directory…</p></div>`,
    },
    {
      id: 'tools-search-and-links', title: 'How search, deep links and permalinks work', category: 'tools',
      summary: 'What the global search indexes, how scoring works, and how to share a link that opens exactly one article, tool, ECU or XDF.',
      tags: ['search', 'deep link', 'permalink', 'url', 'hash', 'index', 'ctrl+k'],
      related: ['getting-started', 'tools-directory'],
      tools: [{ label: 'Open global search', view: 'help', selector: '#helpOpenSpotlightBtn' }],
      body: `
<h3>What is indexed</h3>
<ul>
  <li>Every guide and reference article in this knowledge base (title, tags, summary and full text).</li>
  <li>Every tool entry: all 14 workspaces, every panel, the dialogs and the workshop bench modules.</li>
  <li>Every wire protocol article, with its transport, baud rate and framing terms.</li>
  <li>The <b>live ECU catalog</b> from <code>/api/catalog</code>: all families, display names, years, transports, confidence and notes.</li>
  <li>The <b>bundled XDF library</b> from <code>/api/maps</code>: every definition with tables/constants/flags/patches counts and fitment.</li>
  <li>The glossary, term by term.</li>
  <li>Menu commands (so “print”, “preferences”, “backup” land on the action, not just the article).</li>
</ul>

<h3>How matching works</h3>
<p>The query is split into tokens. A result must match <b>every</b> token somewhere (title, tags, summary, body), and results are ranked by where the match landed: title &gt; tags &gt; summary &gt; body. Exact title prefixes and phrase matches get a bonus. Matching is case- and accent-insensitive, and <code>-</code>, <code>_</code> and <code>.</code> are treated as separators so <code>5am</code>, <code>5-AM</code> and <code>IAW5AM</code> all find the same family.</p>

<h3>Brand scope</h3>
<p>Both the Tools bench and this help center filter by manufacturer. <b>General</b> holds the universal helpers (service intervals, gearing, shim arithmetic, capture decoders, ECU cross-reference), and each brand group holds only that maker&rsquo;s modules. A brand filter narrows tool entries; it never hides a guide, so a Harley workflow is still readable while Honda is selected.</p>

<h3>Scopes</h3>
<p>The spotlight has three scopes: <b>Everything</b>, <b>Guides &amp; Reference</b> and <b>Tools &amp; Views</b>, plus <b>ECUs &amp; XDFs</b> when catalog data is loaded. <kbd>Ctrl</kbd>+<kbd>K</kbd> opens it from anywhere; <kbd>F1</kbd> opens this center.</p>

<h3>Permalinks</h3>
<table class="help-table"><thead><tr><th>Link</th><th>Opens</th></tr></thead><tbody>
<tr><td><code>#help/&lt;topic&gt;</code></td><td>an article, e.g. <code>#help/howto-backup-basemap</code></td></tr>
<tr><td><code>#help/tool/&lt;tool&gt;</code></td><td>a tool entry, e.g. <code>#help/tool/maps-panel</code></td></tr>
<tr><td><code>#help/protocol/&lt;id&gt;</code></td><td>a protocol, e.g. <code>#help/protocol/kwp2000</code></td></tr>
<tr><td><code>#help/ecu/&lt;id&gt;</code></td><td>a catalog ECU, e.g. <code>#help/ecu/5am</code></td></tr>
<tr><td><code>#help/xdf/&lt;filename&gt;</code></td><td>a bundled XDF definition</td></tr>
<tr><td><code>#help/glossary/&lt;term&gt;</code></td><td>the glossary, scrolled to one term</td></tr>
</tbody></table>
<p>Every article has a <b>Copy link</b> button that copies its absolute URL, and the hash updates as you browse so the browser’s back button works.</p>`,
    },
    {
      id: 'tools-keyboard-shortcuts', title: 'Keyboard shortcuts & navigation', category: 'tools',
      summary: 'Every shortcut and navigation rule: global search, help, explorer dock, print, view switching and the search-spotlight keys.',
      tags: ['keyboard', 'shortcuts', 'hotkeys', 'ctrl+k', 'f1', 'navigation', 'accessibility'],
      related: ['tools-search-and-links', 'getting-started'],
      body: `
<table class="help-table"><thead><tr><th>Shortcut</th><th>Action</th></tr></thead><tbody>
<tr><td><kbd>Ctrl</kbd>+<kbd>K</kbd> / <kbd>Cmd</kbd>+<kbd>K</kbd></td><td>Global search spotlight (everything in the program).</td></tr>
<tr><td><kbd>F1</kbd></td><td>Open Help &amp; guides.</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>,</kbd></td><td>Preferences.</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>B</kbd></td><td>Show/hide the explorer dock.</td></tr>
<tr><td><kbd>Ctrl</kbd>+<kbd>P</kbd></td><td>Print / save the current view as PDF.</td></tr>
<tr><td><kbd>Alt</kbd>+<kbd>Q</kbd></td><td>Exit the desktop application (confirmation optional in Preferences).</td></tr>
<tr><td><kbd>Esc</kbd></td><td>Close menus, dialogs and the search spotlight.</td></tr>
<tr><td><kbd>↑</kbd> <kbd>↓</kbd> / <kbd>Enter</kbd></td><td>Move through spotlight results / open the highlighted result.</td></tr>
<tr><td><kbd>1</kbd>–<kbd>5</kbd></td><td>View menu workspace shortcuts (Garage, Gauge Dash, XDF/ROM, DTC, Bench).</td></tr>
</tbody></table>
<p>In the map editor, <kbd>Enter</kbd> commits a cell edit and <kbd>Esc</kbd> abandons it. Undo/redo buttons sit above the grid; the shortcut is shown on the button.</p>
<h3>Navigation rules</h3>
<ul>
  <li>The sidebar and the perspective tabs both switch workspaces. The perspective tabs also remember which view you were last in for that perspective.</li>
  <li>In-page filters (firmware: maps/backup/write; tools: category) persist while you stay in the view.</li>
  <li>Deep links in this help center jump to a panel, expand its <code>&lt;details&gt;</code> card if it is collapsed, and briefly outline it so you can see where you landed.</li>
</ul>`,
    },
  ];

  window.GOB_HELP.topics = TOPICS;
}());

/* ======================================================================
 * TOPICS — protocols overview, ECU reference, checksums, safety.
 * ==================================================================== */
(function () {
  'use strict';

  const TOPICS = [
    {
      id: 'protocols-overview', title: 'Wire protocols: choosing the right transport', category: 'protocols',
      summary: 'The decision table from “what does this ECU speak?” to the exact Garage settings, plus why a connector shape never proves a protocol.',
      tags: ['protocol', 'transport', 'kline', 'can', 'j1850', 'ttl', 'choose', 'adapter', 'overview'],
      related: ['protocol-kwp2000', 'protocol-can-iso-tp', 'protocol-iso9141', 'protocol-j1850', 'protocol-buell-ddfi'],
      tools: [
        { label: 'Garage connection', view: 'garage', selector: '#connectionPanel' },
        { label: 'Protocol evidence', view: 'garage', selector: '#protocolPanel' },
        { label: 'Equipment guide', view: 'equipment' },
      ],
      body: `
<h3>Decision table</h3>
<table class="help-table"><thead><tr><th>If the ECU speaks…</th><th>Garage transport</th><th>Interface</th><th>Read the protocol article</th></tr></thead><tbody>
<tr><td>KWP2000 / ISO 14230 K-Line (IAW 5AM, 7SM, many Guzzi/Ducati)</td><td>K-Line</td><td>USB KKL / FTDI with K-Line transceiver</td><td><a href="#help/protocol/kwp2000">KWP2000</a></td></tr>
<tr><td>ISO 9141-2 OBD (some Triumph)</td><td>K-Line</td><td>KKL / FTDI</td><td><a href="#help/protocol/iso9141">ISO 9141-2</a></td></tr>
<tr><td>Marelli legacy IAW (16M)</td><td>K-Line</td><td>KKL / FTDI</td><td><a href="#help/protocol/legacy-iaw">Legacy IAW</a></td></tr>
<tr><td>UDS / KWP-on-CAN / ISO-TP</td><td>CAN</td><td>SLCAN, SocketCAN, PCAN, J2534</td><td><a href="#help/protocol/can-iso-tp">CAN &amp; ISO-TP</a></td></tr>
<tr><td>J1850 VPW (older Harley)</td><td>ELM / J1850</td><td>Serial ELM327 with VPW support</td><td><a href="#help/protocol/j1850">J1850 VPW</a></td></tr>
<tr><td>Buell DDFI</td><td>TTL serial</td><td>5 V TTL Buell cable</td><td><a href="#help/protocol/buell-ddfi">Buell DDFI</a></td></tr>
<tr><td>rusEFI aftermarket</td><td>Serial console</td><td>USB CDC ACM</td><td><a href="#help/protocol/rusefi-serial">rusEFI</a></td></tr>
<tr><td>Dynojet dyno telemetry</td><td>No ECU transport</td><td>Local network (UDP multicast)</td><td><a href="#help/protocol/jetdrive">JetDrive</a></td></tr>
</tbody></table>

<h3>Facts that are not interchangeable</h3>
<ul>
  <li><b>Connector shape</b> does not identify a protocol. The same 3-pin or 16-pin shell carries K-Line, CAN, J1850 or TTL on different bikes.</li>
  <li><b>A USB serial chip is not a K-Line interface.</b> You need the transceiver, echo handling and the right baud rates.</li>
  <li><b>ISO-TP is not a diagnostic protocol.</b> It is a way to carry messages; UDS, KWP-on-CAN and proprietary dialects sit on top.</li>
  <li><b>OBD-II is a service set, not a wire.</b> It can run over ISO 9141-2, J1850 or CAN.</li>
  <li><b>A cable never unlocks an ECU.</b> Capability comes from the catalog profile and the implemented code, not the hardware you plug in.</li>
</ul>

<h3>How the workstation decides</h3>
<p>Each catalog profile declares its transport, baud rate, init method, addresses, framing and — critically — an <b>evidence note</b> and a confidence level. Where the evidence is a compatibility list rather than a wire definition, the profile has no capabilities and physical use is refused. The <a href="#help/tool/protocol-panel">Protocol evidence</a> card in the Garage shows the evidence for the selected profile, and signed protocol updates can only add read-level behaviour that a qualifying hardware confirmation supports.</p>

<h3>Initialisation cheat-sheet</h3>
<ul>
  <li><b>Fast init</b> (KWP2000): 300 ms idle → 25 ms low → release at 50 ms → StartCommunication → validated <code>C1</code> + 2 keys.</li>
  <li><b>5-baud</b> (KWP2000 or ISO 9141-2): 300 ms idle → 5-baud address → <code>55 KW1 KW2</code> → <code>~KW2</code> → <code>~address</code>. Keywords choose the message protocol.</li>
  <li><b>Legacy IAW</b>: key-on init at 1,200 baud, then 7,680 baud register queries.</li>
  <li><b>CAN</b>: no handshake — configure the bitrate and send the first diagnostic request.</li>
</ul>`,
    },
    {
      id: 'protocol-evidence', title: 'Evidence, confidence levels and signed protocol updates', category: 'protocols',
      summary: 'What the five confidence levels mean, how a capability gets implemented, and what a signed protocol update can and cannot change.',
      tags: ['evidence', 'confidence', 'verified', 'signed', 'updates', 'research', 'trusted key'],
      related: ['protocols-overview', 'safety-blocked-capabilities'],
      tools: [{ label: 'Protocol evidence card', view: 'garage', selector: '#protocolPanel' }],
      body: `
<h3>Confidence levels</h3>
<table class="help-table"><thead><tr><th>Level</th><th>Meaning</th><th>What you should assume</th></tr></thead><tbody>
<tr><td><b>verified-capture</b></td><td>A real capture or transcript from this family establishes the wire behaviour (e.g. the IAW 5AM capture).</td><td>The framing, addresses and scalings that the capture covers are trustworthy; anything outside the capture is not.</td></tr>
<tr><td><b>verified-bench</b></td><td>Confirmed on hardware on a bench by this project.</td><td>Highest confidence available; still not a warranty for your unit.</td></tr>
<tr><td><b>documented</b></td><td>A primary publication or open implementation defines it.</td><td>Structurally sound; your software version may differ.</td></tr>
<tr><td><b>inferred</b></td><td>Compatibility evidence plus adjacent-family knowledge; details are not published.</td><td>Capabilities are usually withheld until a capture exists.</td></tr>
<tr><td><b>unknown</b></td><td>Only a compatibility list or commercial tool exists.</td><td>Zero capabilities. Physical use refused.</td></tr>
</tbody></table>

<h3>How a capability is added</h3>
<ol>
  <li>A primary source, transcript or bench measurement defines the exchange.</li>
  <li>The profile gains a bounded, testable implementation with synthetic tests.</li>
  <li>The evidence note names the source and what is <i>not</i> proven.</li>
  <li>Write capabilities additionally require checksum verification, recovery handling and an explicit gate.</li>
</ol>

<h3>Signed protocol updates</h3>
<p>The desktop checks for published signed packs at startup and periodically. A pack carries a trusted key id and a catalog revision; the workstation verifies the signature and revision before applying anything, keeps a revert history, and only applies changes that add read-level behaviour supported by a qualifying confirmation. Trusted keys can be pinned in the protocol evidence card, and unpinned keys are refused.</p>
<div class="gate-card warn"><h4>Not a firmware update channel</h4><p>Protocol updates change the workstation’s description of a protocol. They never flash an ECU, and they cannot add a write path.</p></div>`,
    },

    /* --------------------------------------------------- ECUs */
    {
      id: 'ecus-overview', title: 'The ECU catalog: every family, transport and capability', category: 'ecus',
      summary: 'A live explorer of every catalog entry, with transport, confidence, capabilities and notes, plus how the catalog is structured.',
      tags: ['ecu', 'catalog', 'family', 'explorer', 'capability', 'coverage'],
      related: ['ecu-confidence', 'ecus-memory-geometry', 'ecus-xdf-library'],
      tools: [{ label: 'Garage vehicle selection', view: 'garage', selector: '#makeSelect' }],
      body: `
<p>Everything the program will do is declared per ECU family in <code>guzzionboard/catalog/ecus/</code>. A vehicle entry points at a family; a family declares its transport, the capabilities that are actually implemented, and the evidence behind them. The list below is generated from the running catalog.</p>
<div id="helpEcuCatalog" class="help-ecu-catalog"><p class="muted">Loading ECU catalog…</p></div>

<h3>How to read an entry</h3>
<ul>
  <li><b>Transport</b> — <code>kline</code>, <code>can</code>, <code>elm_j1850</code>, <code>none</code> (reference-only).</li>
  <li><b>Confidence</b> — see <a href="#help/ecu-confidence">Confidence levels</a>.</li>
  <li><b>Capabilities</b> — <code>identify</code>, <code>live</code>, <code>dtc_read</code>, <code>dtc_clear</code>, <code>actuators</code>, <code>routines</code>, <code>memory_read</code>, <code>eeprom_read</code>, <code>discover</code>, <code>self_adaptation_reset</code>, <code>tps_reset</code>. Empty means nothing is implemented.</li>
  <li><b>Memory</b> — image size, read/write support and the exact reason a write is blocked.</li>
  <li><b>Notes</b> — the honest summary of what is proven and what is not.</li>
</ul>
<p>If a motorcycle you own is missing, the correct fix is a contributed capture with its evidence, not guessing an identifier. See <a href="#help/topic-ecu-confidence">Confidence levels</a> for what a new entry would need.</p>`,
    },
    {
      id: 'ecus-xdf-library', title: 'The bundled XDF library', category: 'ecus',
      summary: 'Every vendored TunerPro definition with its table, constant, flag and patch counts, brand, family and fitment — searchable and jumpable.',
      tags: ['xdf', 'library', 'definitions', 'tunerpro', 'tables', 'bundled', 'provenance'],
      related: ['howto-xdf-editing', 'topic-checksums-xdf-math', 'ecus-overview'],
      tools: [{ label: 'Maps & tables', view: 'firmware', selector: '#mapsCard' }],
      body: `
<p>The library ships with the application so you do not have to hunt for a definition before you can read a map. Files live in <code>guzzionboard/xdfs/</code>; your own go in <code>~/.guzzionboard/xdfs/</code>.</p>
<div id="helpXdfLibrary" class="help-xdf-library"><p class="muted">Loading XDF library…</p></div>

<h3>Provenance and licensing</h3>
<ul>
  <li>The GuzziDiag/IAWDiag archive files are third-party, community-authored definitions, published free for non-commercial use with a “use at your own risk” posture. They are mirrored for diagnostic/tuning reference and are <b>not</b> covered by this application’s software licence.</li>
  <li><code>guzzionboard/xdfs/PROVENANCE.json</code> records the upstream URL, SHA-256 and retrieval date for every vendored file.</li>
  <li>If a definition is inaccurate, the fix is to replace it with a newer upstream version — not to hand-edit the vendored copy.</li>
  <li>A definition rendering successfully does not prove its scalings are right for your software version.</li>
</ul>`,
    },
    {
      id: 'ecu-confidence', title: 'ECU confidence levels and what “research” means', category: 'ecus',
      summary: 'The evidence ladder from verified bench work down to a bare compatibility list, and the rules this project follows at each level.',
      tags: ['confidence', 'evidence', 'research', 'verified', 'inferred', 'unknown', 'bench'],
      related: ['protocol-evidence', 'ecus-overview', 'safety-blocked-capabilities'],
      body: `
<h3>The ladder</h3>
<ol>
  <li><b>verified-bench</b> — measured on hardware by this project, with the procedure recorded.</li>
  <li><b>verified-capture</b> — a real capture/transcript from this exact family establishes the wire behaviour (the IAW 5AM profile).</li>
  <li><b>documented</b> — a primary document or open implementation defines the exchange (IAW 16M, several research profiles).</li>
  <li><b>inferred</b> — tooling compatibility plus adjacent-family knowledge; details unpublished.</li>
  <li><b>unknown</b> — compatibility list only. No capabilities, no physical sessions.</li>
</ol>

<h3>What “research” means in this program</h3>
<ul>
  <li>The exchange is implemented from a third-party source and covered by <b>synthetic tests only</b>; nobody in this project has verified it on a motorcycle.</li>
  <li>Values are labelled candidates where the scaling is uncertain.</li>
  <li>Memory, checksum and write operations are withheld unless the source defines them and a recovery path exists.</li>
  <li>Panels that touch hardware require an explicit confirmation and state the risk in the first paragraph.</li>
</ul>

<h3>What it would take to upgrade an entry</h3>
<ol>
  <li>A capture or transcript taken from the exact model/ECU, with the adapter, baud rate and conditions recorded.</li>
  <li>Repeatability: at least two independent sessions agreeing.</li>
  <li>For memory: region geometry, security exchange and a read that is verified by a second read.</li>
  <li>For writes: checksum generation, power-loss handling and a proven recovery path.</li>
</ol>
<p>Only then does the catalog grow a capability. Compatibility with a commercial tool is never accepted as a protocol definition.</p>`,
    },
    {
      id: 'ecus-memory-geometry', title: 'ECU memory, regions and image sizes', category: 'ecus',
      summary: 'How memory regions are declared, the IAW 5AM geometry, why 304 KiB and 320 KiB images both exist, and what a region name means.',
      tags: ['memory', 'regions', 'geometry', 'image size', '5am', 'flash', 'eeprom', '0x4000'],
      related: ['howto-backup-basemap', 'topic-write-path', 'ecu-5am'],
      tools: [
        { label: 'Backup panel', view: 'firmware', selector: '#backupPanel' },
        { label: 'Compare images', view: 'firmware', selector: '#memoryComparePanel' },
      ],
      body: `
<h3>Regions</h3>
<p>A profile declares named regions with a start address, a size, a block size and a writable flag. The UI only offers the regions the profile declares: reading <code>eeprom</code> is meaningful on the 5AM, meaningless on a profile with no EEPROM path.</p>

<h3>IAW 5AM geometry</h3>
<table class="help-table"><thead><tr><th>Item</th><th>Value</th></tr></thead><tbody>
<tr><td>Flash region start</td><td><code>0x4000</code></td></tr>
<tr><td>Flash region size</td><td><code>0x4C000</code> = 311,296 bytes (304 KiB)</td></tr>
<tr><td>Profile <code>image_size</code></td><td>327,680 bytes (320 KiB, <code>0x50000</code>)</td></tr>
<tr><td>Read blocks</td><td>19 flash blocks, skipped blocks reported explicitly</td></tr>
<tr><td>Approximate read time</td><td>~20 minutes at 10,400 baud</td></tr>
<tr><td>Readback verification</td><td>15 blocks compared after a write</td></tr>
</tbody></table>
<p>The 320 KiB file is the GuzziDiag/IAW5xReader <b>full dump</b>: a 0x4000 bootloader prefix plus the 304 KiB calibration. Attesting one slices <code>[0x4000:0x50000]</code> and reports <i>sliced_from_full_dump</i>. A 304 KiB file is used as-is. Both are accepted; the hash recorded is of the bytes actually used.</p>

<h3>Hardware family</h3>
<p>Image validation extracts hardware strings and compares them to the identified ECU hardware ID. An HW1xx image in an HW3xx ECU is refused with no override — this is the single most common bricking mistake in Marelli flashing.</p>

<h3>Other families</h3>
<ul>
  <li><b>IAW 16M</b>: no in-circuit memory path; maps live in a socketed EPROM.</li>
  <li><b>7SM</b>: identification and session only, no validated geometry.</li>
  <li><b>Harley Delphi</b>: 160 KiB calibration region, 16 KiB tune region (research).</li>
  <li><b>Buell DDFI</b>: EEPROM maps rendered through bundled XDFs.</li>
  <li><b>Honda / Yamaha / Bajaj / CFMoto</b>: image sizes are fixed per research tool and stated on the panel (e.g. 768 KiB Bajaj, 10,248-byte Juken block).</li>
</ul>`,
    },
    {
      id: 'ecu-iaw-family', title: 'Magneti Marelli IAW family (5AM, 7SM, 16M, 15M, MIU, 11MP)', category: 'ecus',
      summary: 'Which IAW variants are catalogued, what each one can do here, and why so many entries deliberately have zero capabilities.',
      tags: ['marelli', 'iaw', '5am', '7sm', '16m', '15m', '15rc', '59m', 'miu', '11mp', 'p8'],
      related: ['ecu-5am', 'protocol-kwp2000', 'protocol-legacy-iaw'],
      body: `
<h3>The Guzzi-relevant variants</h3>
<table class="help-table"><thead><tr><th>Family</th><th>Years</th><th>Status here</th></tr></thead><tbody>
<tr><td><b>IAW 5AM / 5AM2</b></td><td>2005–2016</td><td>Capture-verified: identify, live, DTCs, actuators, resets, 19-block flash read, SecurityAccess, gated write path.</td></tr>
<tr><td><b>IAW 7SM</b></td><td>2017+</td><td>Fast-init K-Line session, identification, baud switch. No memory path.</td></tr>
<tr><td><b>IAW 16M</b></td><td>1996–2001</td><td>Documented legacy register protocol: identify, live (raw counts where scaling is disputed), DTC read.</td></tr>
<tr><td><b>IAW 15M / 15RC</b></td><td>1997–2012</td><td>Catalogued, zero capabilities: tooling exists, no public wire definition or capture.</td></tr>
<tr><td><b>IAW 59M</b></td><td>2001–2009</td><td>Ducati applications, zero capabilities (GuzziDiag/TuneECU compatibility only).</td></tr>
<tr><td><b>MIU G3 / MIU G4</b></td><td>2010s</td><td>MIU G3 has OEM identifier names but no framing/scaling — blocked. MIU G4 is CAN, no identifiers — blocked.</td></tr>
<tr><td><b>11MP</b></td><td>2019–2026</td><td>Euro 5 CAN controller; no published identifier pair or DID table — blocked.</td></tr>
<tr><td><b>P8</b></td><td>1990s</td><td>Catalogued reference only.</td></tr>
</tbody></table>

<h3>Why zero capabilities is the right answer</h3>
<p>A dedicated reader/writer existing (GuzziDiag, IAWDiag, commercial tools) proves a path exists — it does not publish the session, geometry, security exchange or block sequence. Guessing a sibling family’s KWP identifiers is exactly how hobby tools corrupt ECUs. Where the definition is not public, this program refuses rather than asking an owner to characterise their own ECU.</p>

<h3>The 5AM in detail</h3>
<p>See <a href="#help/ecu-5am">IAW 5AM deep dive</a> for the capture-verified parameter set, 38 of 79 answerable identifiers, the session <code>0x81</code> behaviour and the write path.</p>`,
    },
    {
      id: 'ecu-5am', title: 'IAW 5AM / 5AM2 deep dive', category: 'ecus',
      summary: 'The capture-verified Guzzi controller: parameter coverage, session handling, memory geometry, security and the gated write path.',
      tags: ['5am', '5am2', 'griso', 'breva', 'norge', 'stelvio', 'capture', 'kwp2000', 'write'],
      related: ['protocol-kwp2000', 'howto-backup-basemap', 'topic-write-path', 'ecus-memory-geometry'],
      tools: [
        { label: 'Garage', view: 'garage' },
        { label: 'Backup', view: 'firmware', selector: '#backupPanel' },
        { label: 'Maps', view: 'firmware', selector: '#mapsCard' },
      ],
      body: `
<h3>Where it is fitted</h3>
<p>Every CARC-framed Moto Guzzi: Breva 850/1100/1200, Griso, Norge, 1200 Sport and Stelvio (2005–2016). Hardware designations such as <b>HW610</b> appear in identification; the hardware family matters for image validation.</p>

<h3>What is capture-verified</h3>
<ul>
  <li>KWP2000 fast init at 10,400 baud, physical addressing, tester <code>0xF1</code> → ECU <code>0x10</code>.</li>
  <li>Diagnostic session <code>0x81</code>; <code>0x85</code> is rejected with NRC <code>0x22</code> outside programming.</li>
  <li>Parameter scalings decoded from a live capture on a real bike: 38 of the 79 answerable identifiers are served as live channels.</li>
  <li>19-block flash read from <code>0x4000</code>, 311,296 bytes, with explicit skipped-block reporting.</li>
  <li>SecurityAccess via the documented <code>5am_util</code> key sequence.</li>
</ul>

<h3>The write path</h3>
<ol>
  <li>Verified dual-read backup → base map vaulted with SHA-256.</li>
  <li>Built image validated for size, structure and hardware family.</li>
  <li>Calibration checksum handled by the declared provider, if the XDF declares one.</li>
  <li>Programming session enabled for the session; the implemented writer unlocked with the recovery acknowledgement because it is not bench-verified by this project.</li>
  <li>Single-use token, then block transfer and a 15-block readback comparison.</li>
</ol>

<h3>What is still unknown</h3>
<p>No bench-confirmed key unlock, no bench-tested recovery path and no power-loss handling have been demonstrated by this project. That is precisely why the writer is gated behind an explicit acknowledgement and why the catalog’s <code>write_supported</code> stays false on disk.</p>`,
    },
    {
      id: 'ecu-harley-family', title: 'Harley-Davidson: Delphi CAN, J1850 and Power Vision', category: 'ecus',
      summary: 'Four different Harley paths — CAN identity research, J1850 VPW read-only, offline Delphi region/PVV work, and off-road experimental memory.',
      tags: ['harley', 'delphi', 'j1850', 'power vision', 'pvv', 'centurion', 'hdlan', 'can'],
      related: ['topic-howto-brand-workflows', 'protocol-j1850', 'protocol-hdlan'],
      tools: [
        { label: 'Harley region workspace', view: 'tools', selector: '#harleyRegion' },
        { label: 'Power Vision PVV', view: 'tools', selector: '#pvvEditor' },
        { label: 'Harley memory', view: 'tools', selector: '#harleyMemory' },
      ],
      body: `
<h3>Path 1 — Delphi CAN identity (research)</h3>
<p>500 kbit/s classic CAN, 0x7E0 request / 0x7E8 response, identity and live data. Dynojet lists these models for its Delphi CAN tool; this integration is synthetic-tested only, and authentication differences may prevent replies.</p>

<h3>Path 2 — J1850 VPW read-only</h3>
<p>HarleyDroid-style diagnostics over a serial ELM327 that supports VPW. Identify, live and DTC read only. No memory access.</p>

<h3>Path 3 — offline Delphi work (recommended)</h3>
<ul>
  <li><b>Calibration region workspace</b>: inspect a 160 KiB calibration or 16 KiB tune, compare regions, export the 16 KiB region. Layout from HarleyECUTool (~2014–2020).</li>
  <li><b>Centurion header research</b>: compare candidate ECU-part and calibration header fields across two files.</li>
  <li><b>Power Vision PVV editor</b>: inspect a PVV XML, edit cells, save a new XML copy. No device connection.</li>
</ul>

<h3>Path 4 — experimental live memory</h3>
<p>The Delphi CAN memory panel reads a calibration and has a 16 KiB tune write. A read sends an authentication payload to ECU address zero, which can alter ECU state. Synthetic-tested only; treat it as research, not a service procedure.</p>

<h3>Practical advice</h3>
<p>For customer work, the offline tools plus a bench programmer are the professional route. Live experimental writes to a Harley Delphi ECU are the least reversible thing in this program.</p>`,
    },
    {
      id: 'ecu-buell', title: 'Buell DDFI ECMs', category: 'ecus',
      summary: 'Live serial read plus experimental fuel/spark EEPROM write, with source-derived XDF maps for offline inspection.',
      tags: ['buell', 'ddfi', 'ecmspy', 'eeprom', 'ttl', 'harley'],
      related: ['protocol-buell-ddfi', 'topic-howto-brand-workflows'],
      tools: [
        { label: 'Buell panel', view: 'tools', selector: '#buellDdfi' },
        { label: 'Buell maps', view: 'firmware', selector: '#mapsCard' },
      ],
      body: `
<h3>Hardware</h3>
<p>DDFI/DDFI-2/DDFI-3 ECMs use a <b>5 V TTL serial</b> diagnostic link. You need the correct Buell cable (or a paired Bluetooth serial adapter), correct voltage and a solid ground. TTL is not RS-232, not K-Line and not J1850.</p>

<h3>What you can do</h3>
<ol>
  <li><b>Identify</b> the ECM and confirm the DDFI generation.</li>
  <li><b>Read live data</b> for the channels the profile implements.</li>
  <li><b>Inspect the EEPROM offline</b> with the bundled Buell XDFs — tables render like any other definition.</li>
  <li><b>Experimental EEPROM write</b> for fuel and spark, in its own collapsed panel, with backup and acknowledgements.</li>
</ol>

<h3>Risk</h3>
<p>Source research (ECMSpy lineage) with synthetic tests only. A bad EEPROM write leaves the ECM unable to run the engine; recovery usually means a bench reflash or a replacement ECM. Prove your recovery path on a spare unit first.</p>`,
    },
    {
      id: 'ecu-honda', title: 'Honda: PGM-FI K-Line, DashBle and calibration checksums', category: 'ecus',
      summary: 'Which Honda entries are live-capable, which are read-only research, and how the two bundled calibration checksum providers are scoped.',
      tags: ['honda', 'pgm-fi', 'keihin', 'dashble', 'cbr', 'cb500', 'checksum', 'mgz'],
      related: ['protocol-honda-pgmfi', 'topic-checksums-plugins', 'protocols-overview'],
      tools: [
        { label: 'Honda decoder', view: 'tools', selector: '#hondaOffline' },
        { label: 'Honda checksum tool', view: 'tools', selector: '#hondaVfrChecksum' },
      ],
      body: `
<h3>Catalog entries</h3>
<ul>
  <li><b>CB500F DashBle table 11</b> — identify and live, K-Line.</li>
  <li><b>CTX700</b>, <b>CBR600RR 2005</b> — live only, source-reported.</li>
  <li><b>Keihin PGM-FI research</b> — identify and live, synthetic-tested.</li>
  <li><b>PGM-FI flash research</b> — identify only, with a flash region declared but no read/write path.</li>
  <li><b>CB500 MGZ-A03</b>, <b>CBR1000RR 2012 US</b> — catalogued, zero capabilities.</li>
</ul>

<h3>Calibration checksums</h3>
<p>Two providers ship, and both are explicitly selected — never auto-applied:</p>
<ul>
  <li>Honda CBR1000RR 2012 US / 38770-MGP-A01.</li>
  <li>Honda CB500F / CBR500R MGZ-A03.</li>
</ul>
<p>Each is locked to its specific XDF and original source-image hash. Neither applies to another Honda calibration, let alone another brand. The source-ID checksum tool additionally compares an original and an edited image, validates the candidate id and the original zero-byte sum, and proposes one checksum byte.</p>

<h3>Offline decoding</h3>
<p>The K-Line decoder accepts complete hex frames and refuses bad checksums. It uses a third-party implementation tested by its author on a 2005 CBR600RR; this project has not validated fitment.</p>`,
    },
    {
      id: 'ecu-suzuki-kawasaki', title: 'Suzuki SDS and Kawasaki KDS profiles', category: 'ecus',
      summary: 'Raw-snapshot K-Line research: which models are covered, what a snapshot contains, and why no memory path exists.',
      tags: ['suzuki', 'kawasaki', 'sds', 'kds', 'kline', 'raw', 'sv650', 'gsx-r', 'v-strom'],
      related: ['protocol-kds-sds', 'protocols-overview'],
      body: `
<h3>Suzuki</h3>
<ul>
  <li>GSX-R / Hayabusa SDS research, SV650 2003–2005, SV650AK7 2007, GSX-R600 2011, GSX-R1000 2004, V-Strom DL650XAL7 2017.</li>
  <li>The SDS integration sends one documented request and exposes a long raw snapshot; the exact request/response bytes come from separate sources.</li>
</ul>
<h3>Kawasaki</h3>
<ul>
  <li>ER-6n 2006, Versys 650 2012, KDS generic research (K-Line).</li>
  <li>Ninja 650 / Z650 / ZX-6R 2023–2026 (CAN research) and Ninja 7 Hybrid (KWP-on-CAN, identify/live/DTC).</li>
</ul>

<h3>What a snapshot is not</h3>
<p>A fixed block of bytes from one request proves the link works. It does not give you ECU identity, fault codes, memory geometry or programming. Several sources explicitly say some conversions may be inaccurate, so every value is presented as a candidate.</p>

<h3>Missing models</h3>
<p>If your bike is not listed, the correct next step is a capture (with the adapter, baud rate and conditions recorded) that can be contributed as evidence — not a guessed identifier table.</p>`,
    },
    {
      id: 'ecu-triumph-other', title: 'Triumph, Yamaha, BMW, Ducati and other research profiles', category: 'ecus',
      summary: 'The remaining catalog families: what is live-capable, what is offline-analysis only, and where the source evidence comes from.',
      tags: ['triumph', 'yamaha', 'bmw', 'ducati', 'indian', 'gasgas', 'research', 'other'],
      related: ['protocol-iso9141', 'protocol-yamaha-dashboard', 'protocol-hdlan'],
      body: `
<h3>Triumph</h3>
<p>2009 Bonneville 865 EFI and 2012 Daytona 675: ISO 9141-2 OBD read-only live data and stored faults. Gauge formulas are the SAE definitions, not dash-verified.</p>

<h3>Yamaha</h3>
<ul>
  <li><b>MT-03 660 (2010)</b>: listen-only 16,064-baud dashboard stream observation.</li>
  <li><b>R9 2026</b>: CAN broadcast research decoder at 500 kbit/s.</li>
</ul>

<h3>Ducati</h3>
<p>Panigale Mitsubishi CAN research decoder (passive, opt-in, rejects unrelated frames), plus 29 bundled XDF definitions across Ducati families for offline map work.</p>

<h3>BMW and others</h3>
<p>The multi-brand offline research tool decodes captures for profiles such as BMW R1300GS. These are candidate interpretations from third-party projects, not vehicle identification.</p>

<h3>The rule for all of them</h3>
<p>Read the panel’s first paragraph. It states whether the integration is hardware-tested by this project, synthetic-tested only, or reference-only. Where it says synthetic-tested only, plan a bench session before you rely on it for a customer bike.</p>`,
    },

    /* --------------------------------------------------- CHECKSUMS */
    {
      id: 'checksums-overview', title: 'Checksums: what they are and the four kinds that matter', category: 'checksums',
      summary: 'Frame checksums, calibration checksum fields, upload/inspection sums and research heuristics — and why they are never interchangeable.',
      tags: ['checksum', 'crc', 'sum', 'frame', 'calibration', 'upload', 'verify', 'repair'],
      related: ['topic-checksums-plugins', 'topic-checksums-xdf-math', 'topic-checksums-validate'],
      tools: [
        { label: 'Checksum providers in Maps', view: 'firmware', selector: '#mapsCard' },
        { label: 'Validate an image', view: 'firmware', selector: '#validatePanel' },
      ],
      body: `
<h3>The four kinds</h3>
<table class="help-table"><thead><tr><th>Kind</th><th>Scope</th><th>Who computes it</th><th>In this program</th></tr></thead><tbody>
<tr><td><b>Frame checksum</b></td><td>One diagnostic message</td><td>Protocol layer (e.g. KWP2000 CS byte)</td><td>Validated on every reply; a bad frame is rejected</td></tr>
<tr><td><b>Calibration checksum</b></td><td>A field inside the flash image, covering defined ranges</td><td>ECU firmware</td><td>Updated only by an explicitly selected provider declared by the XDF</td></tr>
<tr><td><b>Upload / integrity sum</b></td><td>A file or transfer</td><td>Tool, loader or transport</td><td>SHA-256 plan locks, readback comparison</td></tr>
<tr><td><b>Research heuristic</b></td><td>A vendor-layout guess</td><td>Third-party research</td><td>Offline inspection panels that never write</td></tr>
</tbody></table>

<h3>Why they are not interchangeable</h3>
<p>Recomputing a frame checksum tells you nothing about the image. Recomputing a calibration checksum with the wrong algorithm produces a file the ECU considers corrupt — sometimes silently, sometimes by refusing to start. An upload hash proves the bytes you sent are the bytes you meant to send; it says nothing about whether the ECU will accept them.</p>

<h3>What the program does when a checksum is declared</h3>
<ul>
  <li>The XDF declares one or more <code>XDFCHECKSUM</code> titles.</li>
  <li>You choose a provider that supports <b>every</b> declared title; providers are never auto-selected.</li>
  <li>Preview and build preserve image length and refuse more than 4096 changed bytes.</li>
  <li>The build record stores provider id, version, source, plugin SHA-256, isolation mode, input/output hashes and every changed byte range.</li>
  <li>A provider that claims hardware verification says so; an unverified provider says that instead.</li>
</ul>

<h3>When there is no provider</h3>
<p>If the image declares a checksum and no provider matches, the build refuses. There is no “ignore checksum” switch, because ignoring it is how a flashing session ends with a dead ECU.</p>`,
    },
    {
      id: 'checksums-plugins', title: 'Checksum plugin providers: writing and installing one', category: 'checksums',
      summary: 'The plugin contract, the isolation model, the size and byte-change limits, and how to test a provider before trusting it.',
      tags: ['plugin', 'provider', 'checksum', 'python', 'isolation', 'sandbox', 'authoring'],
      related: ['topic-checksums-overview', 'topic-safety-gates'],
      tools: [{ label: 'Maps & checksum selector', view: 'firmware', selector: '#mapsCard' }],
      body: `
<h3>Where they live</h3>
<p><code>~/.guzzionboard/checksums/</code>. A plugin is a Python file defining:</p>
<pre><code>PROVIDER_ID = "owner.algorithm-v1"
NAME = "Documented ECU checksum"
VERSION = "1.0.0"
SUPPORTED_CHECKSUMS = ("Exact XDFCHECKSUM title",)
VERIFIED = False
NOTE = "Algorithm source, test vectors, ECU/software, physical test status"

def update(image: bytes, context: dict) -&gt; bytes:
    # Return same-length bytes; do not touch unrelated data
    ...

def verify(image: bytes, context: dict) -&gt; bool:
    ...</code></pre>

<h3>Isolation</h3>
<p>Plugins are <b>never imported into the server process</b>. Metadata inspection and every calculation run in a fresh <code>python -I -S -B</code> subprocess with a clean temporary directory and environment. The worker applies a four-second parent timeout, a two-second CPU limit, a 256 MiB address-space cap, a 1 MiB file-size cap, low descriptor and child-process limits, and an audit hook denying network sockets, subprocess creation, environment mutation, filesystem writes and reads outside the plugin and the standard library. Two calculations run in separate fresh workers and must produce identical bytes, followed by provider verification, and the plugin hash is rechecked immediately before execution.</p>
<div class="gate-card warn"><h4>Containment, not a kernel sandbox</h4><p>This is strong protection against mistakes and ordinary malice, but the plugin is still native Python running as your user. Only install code you are willing to trust.</p></div>

<h3>Writing one safely</h3>
<ol>
  <li>Start from the ECU’s documented algorithm and a known-good image pair.</li>
  <li>Assert <b>length is unchanged</b> and only the declared checksum bytes differ.</li>
  <li>Include test vectors in your own notes; the program records hashes but cannot prove the algorithm.</li>
  <li>Mark <code>VERIFIED = False</code> unless you have bench evidence. Claiming verification you do not have is worse than admitting you have none.</li>
  <li>Test on a simulator build and a spare ECU before a customer bike.</li>
</ol>

<h3>Bundled providers</h3>
<p>Two Honda providers ship in-process (CBR1000RR 2012 US / 38770-MGP-A01 and CB500F/CBR500R MGZ-A03), each locked to its XDF and source-image hash. They are selected explicitly, like any other provider.</p>`,
    },
    {
      id: 'checksums-xdf-math', title: 'XDF reference: math, floats, bit flags, patches and cross-table equations', category: 'checksums',
      summary: 'How TunerPro equations are evaluated and inverted, how IEEE-754 and strides work, how THAT(...) resolves other tables, and how flags and patches are encoded.',
      tags: ['xdf', 'math', 'equation', 'ieee754', 'float', 'mmedtypeflags', 'flag', 'patch', 'that', 'stride', 'conversion'],
      related: ['howto-xdf-editing', 'topic-checksums-overview'],
      tools: [{ label: 'Maps & tables', view: 'firmware', selector: '#mapsCard' }],
      body: `
<h3>Equations</h3>
<p>Each table or constant carries a conversion from raw integer to engineering value, plus the reverse. Supported operators include <code>+ - * /</code>, parentheses, decimal and hex literals (<code>0x1F</code>), bit shifts <code>&lt;&lt;</code> and <code>&gt;&gt;</code>, and the XDF functions. Evaluation is deterministic and rounded only at display time; the reverse path solves for the raw value rather than guessing it.</p>

<h3>IEEE-754 floats</h3>
<p>32-bit and 64-bit floats are decoded when the XDF declares them (the <code>mmedtypeflags</code> bits <code>0x04</code> and <code>0x10000</code>). Float maps show real numbers with the raw hex beside them; the reverse path re-encodes an edited value exactly. NaN and infinity are reported, never silently displayed as zero.</p>

<h3>Cross-table references — <code>THAT(...)</code></h3>
<p>An equation can read another table at a computed row/column, which is how XDFs express load-dependent limits and corrections:</p>
<pre><code>THAT(id; ROW(); COL(); FALSE)</code></pre>
<ul>
  <li><b>id</b> — the target table/constant id.</li>
  <li><b>ROW()</b> and <b>COL()</b> — expressions for the target coordinates (the parentheses are part of the syntax).</li>
  <li><b>4th argument</b> — <code>TRUE</code> returns the raw stored value, <code>FALSE</code> returns the engineering value.</li>
</ul>
<p>Cycles and out-of-range coordinates are rejected when the definition is validated, so a malicious or broken XDF cannot recurse forever.</p>

<h3>Strides and layout</h3>
<p>Tables are stored with an explicit row stride; <b>column-major</b> definitions are supported (the Z axis declares the stride). Cell size, endianness and signedness come from the XDF. If a rendered table looks like noise, check endianness before assuming the definition is wrong.</p>

<h3>Bit flags (<code>&lt;XDFFLAG&gt;</code>)</h3>
<p>A flag is an address plus a mask. Toggling writes the mask and preserves every sibling bit in the same byte; the panel shows the byte before and after. The serialized form includes <code>mask</code>, <code>mask_int</code>, <code>raw</code>, <code>value</code> (boolean), <code>size_bits</code> and <code>editable</code>, so an external tool can reproduce the edit.</p>

<h3>Binary patches (<code>&lt;XDFPATCH&gt;</code>)</h3>
<p>A patch is a set of spans with expected base bytes and replacement bytes. Its state is <b>applied</b>, <b>unapplied</b> or <b>mismatch</b>. Apply/revert is permitted when the current bytes match the expected base; a mismatch requires an explicit confirmation (<code>allow_base_mismatch</code>) and is recorded with the observed hex. This is the optimistic lock that stops a patch designed for one software version from silently corrupting another.</p>

<h3>Validation</h3>
<p>The definition validator checks ids, addresses against the declared region, axis lengths, math syntax, <code>THAT(...)</code> targets and cycles, patch spans, and checksum titles. It is run before a definition is used for a build.</p>`,
    },
    {
      id: 'checksums-validate', title: 'Image validation, comparison and readback', category: 'checksums',
      summary: 'The four checks a candidate image must pass, how to compare two reads, and why a readback is part of a write.',
      tags: ['validate', 'readback', 'compare', 'image', 'hardware family', 'entropy', 'vector', 'verify'],
      related: ['topic-write-path', 'howto-backup-basemap', 'checksums-overview'],
      tools: [
        { label: 'Validate', view: 'firmware', selector: '#validatePanel' },
        { label: 'Compare images', view: 'firmware', selector: '#memoryComparePanel' },
      ],
      body: `
<h3>The four checks</h3>
<ol>
  <li><b>Size</b> — must match a declared region size, not merely “look right”.</li>
  <li><b>Vector table</b> — the reset/interrupt vectors must be plausible for the family.</li>
  <li><b>Entropy</b> — an image that is mostly 0xFF or mostly random is not a calibration.</li>
  <li><b>Hardware family</b> — hardware strings extracted from the image must match the identified ECU. Mismatch is refused without override.</li>
</ol>

<h3>Comparing two images</h3>
<p>Byte-level comparison, with counts and ranges. Use it to:</p>
<ul>
  <li>Confirm two reads are identical (repeatability).</li>
  <li>Confirm a built image differs from the base only where you intended.</li>
  <li>Confirm a readback matches what you wrote.</li>
</ul>
<p>Identical bytes do not prove completeness, correct layout or restorability. Two identical bad reads are still a bad backup.</p>

<h3>Readback is part of the write</h3>
<p>After writing, the workstation re-reads the region and compares it block by block (15 blocks on the 5AM). A write without readback is not verified, and the session log records both the transfer and the comparison result.</p>

<h3>Hashes you will see</h3>
<ul>
  <li><b>Image SHA-256</b> — of the file on disk.</li>
  <li><b>Base map SHA-256</b> — re-checked every time a write is considered.</li>
  <li><b>Plan SHA-256</b> — of the input image plus change set, which locks a build to its inputs.</li>
  <li><b>Plugin SHA-256</b> — rechecked immediately before a checksum calculation.</li>
</ul>`,
    },
  ];

  window.GOB_HELP.topics = window.GOB_HELP.topics.concat(TOPICS);
}());

/* ======================================================================
 * TOPICS — safety, write path and troubleshooting.
 * ==================================================================== */
(function () {
  'use strict';

  const TOPICS = [
    {
      id: 'safety-gates', title: 'Safety gates: what must be true before anything moves', category: 'safety',
      summary: 'The gate model — capability, evidence, hardware family, base map, backup, token — with the exact acknowledgement text you will be asked to type or tick.',
      tags: ['safety', 'gate', 'acknowledgement', 'token', 'capability', 'base map', 'backup', 'risk'],
      related: ['write-path', 'safety-recovery', 'protocol-security-access'],
      tools: [
        { label: 'Write gate', view: 'firmware', selector: '#writePanel' },
        { label: 'Writer unlock', view: 'firmware', selector: '#writerUnlockDetails', openDetails: '#writerUnlockDetails' },
      ],
      body: `
<h3>The model</h3>
<p>Every risky operation is evaluated by the same gate, and the gate returns a <b>decision with reasons</b>, not a boolean. A refusal lists each failed check with a sentence you can act on. Decisions are recorded in the session log.</p>
<table class="help-table"><thead><tr><th>Layer</th><th>Question</th><th>If it fails</th></tr></thead><tbody>
<tr><td>Capability</td><td>Does this profile implement the operation?</td><td>Refused, with the profile’s reason.</td></tr>
<tr><td>Evidence</td><td>Is the profile allowed to do it on hardware?</td><td>Research/simulator-only, or refused.</td></tr>
<tr><td>Session</td><td>Connected, identified, correct engine state?</td><td>Refused until the state matches.</td></tr>
<tr><td>Hardware family</td><td>Does the image match the identified ECU?</td><td>Refused — no override.</td></tr>
<tr><td>Base map</td><td>Is a re-hashed vaulted original present?</td><td>Refused; writes are impossible without a way back.</td></tr>
<tr><td>Token</td><td>Is this exact operation confirmed, once?</td><td>Refused; tokens are single-use and content-locked.</td></tr>
<tr><td>Opt-in</td><td>Programming enabled for this session?</td><td>Refused; nothing is enabled by default.</td></tr>
</tbody></table>

<h3>Exact acknowledgements</h3>
<table class="help-table"><thead><tr><th>When</th><th>What you must state, verbatim</th></tr></thead><tbody>
<tr><td>Enabling programming for a session</td><td><code>I have a verified backup and accept the risk</code></td></tr>
<tr><td>Unlocking an implemented but unverified hardware writer</td><td><code>I have an external recovery plan and accept unverified ECU write risk</code></td></tr>
<tr><td>Attesting an external full backup</td><td><code>I confirm this file is a verified full backup from this exact ECU</code></td></tr>
<tr><td>Building a modified calibration</td><td><code>I understand modified maps can damage the engine and accept responsibility</code></td></tr>
</tbody></table>
<p>These strings are stored in the code and compared exactly. They are not “click to continue” dialogs: the point is that you read the sentence.</p>

<h3>Actuators and resets</h3>
<p>Actuator tests are bounded by the workstation, not by the ECU. IAW ECUs have no output timer, so the workstation holds the deadline and releases on expiry, on disconnect and if the browser goes away. Adaptation resets are irreversible and always gated by engine state.</p>

<h3>What the gate does not do</h3>
<ul>
  <li>It does not decide whether a change is <i>good</i> — that is engineering judgement.</li>
  <li>It does not prove a checksum algorithm is correct on your ECU.</li>
  <li>It cannot see a failing battery, a loose ground or a bad cable. Those are your pre-flight.</li>
</ul>`,
    },
    {
      id: 'write-path', title: 'The write path: from backup to readback', category: 'safety',
      summary: 'The full ordered sequence a write follows in code, including programming services, block transfer, verification and what happens when something fails.',
      tags: ['write', 'programming', 'sequence', 'transfer', 'readback', 'request download', 'session', 'token'],
      related: ['safety-gates', 'howto-custom-build-and-flash', 'ecu-5am', 'safety-recovery'],
      tools: [
        { label: 'Write panel', view: 'firmware', selector: '#writePanel' },
        { label: 'Validate', view: 'firmware', selector: '#validatePanel' },
      ],
      body: `
<h3>Ordered sequence</h3>
<ol>
  <li><b>Backup</b> — dual read, byte-identical, hashed. Base map vaulted.</li>
  <li><b>Build</b> — the calibration is produced from a locked plan (input hash + change set). Checksum provider selected explicitly if declared.</li>
  <li><b>Validate</b> — size, vector table, entropy, hardware family.</li>
  <li><b>Enable programming</b> — per-session opt-in with the acknowledgement.</li>
  <li><b>Unlock writer</b> — only for families whose write sequence is implemented but not bench-verified (e.g. IAW 5AM). Per-session; raises the effective capability without editing the catalog on disk.</li>
  <li><b>Confirmation token</b> — built from the exact operation (region, image hash, checks) and verified once.</li>
  <li><b>Exclusive session</b> — the ECU session is held; no live polling or other commands run concurrently.</li>
  <li><b>Enter programming session</b> → SecurityAccess (documented key sequence or a provider) → RequestDownload (0x34) → TransferData (0x36) → RequestTransferExit (0x37).</li>
  <li><b>Readback</b> — the region is re-read and compared block by block (15 blocks on 5AM).</li>
  <li><b>Record</b> — decision, token, hashes, byte ranges, readback result and any failure are written to the session log.</li>
</ol>

<h3>Failure behaviour</h3>
<ul>
  <li>A refused precondition means <b>nothing is transmitted</b>. Refusals are cheap; half-flashes are not.</li>
  <li>A transport failure mid-transfer aborts and reports the last acknowledged block, so a recovery attempt has a starting point.</li>
  <li>A readback mismatch is reported as a failure even if every transfer acknowledged — the ECU is the authority.</li>
  <li>Tokens are invalidated by any material change, including a re-read that changes the base map hash.</li>
</ul>

<h3>What is implemented on hardware now</h3>
<p>Only the read path is bench-verified for the IAW 5AM. The write sequence exists, is simulator-tested, and requires the unverified-writer acknowledgement. Other families either have no write sequence or are explicitly blocked with a reason in their catalog entry.</p>`,
    },
    {
      id: 'safety-recovery', title: 'Recovery: plan it before you need it', category: 'safety',
      summary: 'A practical recovery plan for a failed flash — power, cabling, a second ECU, bench options and what the program can and cannot do for you.',
      tags: ['recovery', 'brick', 'failed flash', 'bench', 'bootloader', 'backup', 'plan'],
      related: ['write-path', 'safety-gates', 'howto-backup-basemap'],
      tools: [{ label: 'Base map vault', view: 'firmware', selector: '#baseMapPanel' }],
      body: `
<h3>Before the write</h3>
<ol>
  <li>Battery on a smart charger, laptop on mains, screen sleep and USB power saving disabled.</li>
  <li>Adapter cable strain-relieved and taped; nobody walks past the bike.</li>
  <li>Verified backup in the vault <b>and</b> on a separate disk (cloud copy is fine).</li>
  <li>A written recovery plan: who can bench-flash it, how far away, what it costs, how the bike gets there.</li>
  <li>For a customer bike: agree the risk in writing before the first byte.</li>
</ol>

<h3>If a write fails</h3>
<ol>
  <li><b>Do not cycle the ignition repeatedly.</b> Read the reported failure first — the last acknowledged block and the readback result are in the session log.</li>
  <li>If the ECU still answers identification, retry the documented write with the same image (not a modified one).</li>
  <li>If it answers nothing, the ECU is in a bootloader/erase state: it needs a bench recovery — BDM/JTAG where supported, a socketed EPROM programmer (16M), or a replacement ECU.</li>
  <li>Record what happened. A recovery attempt that also fails still narrows the cause.</li>
</ol>

<h3>What this program provides</h3>
<ul>
  <li>The vaulted base map with its hash, so a recovery target is unambiguous.</li>
  <li>Image comparison, to confirm what you actually sent.</li>
  <li>Session logs with every decision, token and byte range.</li>
  <li>No remote “unbrick” service: a bench recovery is a physical procedure.</li>
</ul>

<div class="gate-card warn"><h4>Honest statement</h4><p>No bench-tested recovery path exists for the IAW 5AM in this project, and power-loss handling has not been demonstrated. That is why hardware writing is opt-in and gated. If you cannot afford to lose the ECU, do not write to it.</p></div>`,
    },
    {
      id: 'safety-troubleshooting', title: 'Troubleshooting: symptoms, causes and fixes', category: 'safety',
      summary: 'A symptom-first table for connection, read, map-rendering, checksum and write problems, with the exact panel that tells you what happened.',
      tags: ['troubleshooting', 'error', 'no response', 'timeout', 'checksum', 'timeout', 'slow', 'fix'],
      related: ['howto-first-connection', 'safety-gates', 'howto-backup-basemap'],
      tools: [
        { label: 'Adapter pre-flight', view: 'firmware', selector: '#adapterPanel' },
        { label: 'Sessions & events', view: 'sessions' },
      ],
      body: `
<h3>Connection</h3>
<table class="help-table"><thead><tr><th>Symptom</th><th>Likely cause</th><th>Fix</th></tr></thead><tbody>
<tr><td>Connect disabled</td><td>Checklist rows unacknowledged, or no device entered</td><td>Work the checklist; enter the port/channel</td></tr>
<tr><td>No response to fast init</td><td>Wrong port, no K-Line transceiver, ignition off, or a 5-baud-only ECU</td><td>Check adapter, key state, try the other init method</td></tr>
<tr><td>Link established, every request times out</td><td>Wrong negotiated protocol (e.g. ISO 9141-2 keywords for a KWP profile) or wrong ECU selection</td><td>Read the Link card, re-check the ECU override</td></tr>
<tr><td>Works in the simulator, not on the bike</td><td>Hardware path differs from simulator; driver or adapter problem</td><td>Adapter pre-flight, latency measurement</td></tr>
<tr><td>CAN interface opens but nothing arrives</td><td>Wrong bitrate, no termination, wrong identifiers</td><td>Configure the interface externally; verify 500 kbit/s; confirm the identifier pair</td></tr>
</tbody></table>

<h3>Memory reads</h3>
<table class="help-table"><thead><tr><th>Symptom</th><th>Likely cause</th><th>Fix</th></tr></thead><tbody>
<tr><td>Read takes hours</td><td>FTDI latency timer at 16 ms</td><td>Set it to 1 ms</td></tr>
<tr><td>Two reads disagree</td><td>Noise, poor ground, unpowered ECU, USB power saving</td><td>Fix wiring/power, disable power saving, retry — nothing is kept unless both agree</td></tr>
<tr><td>Block skipped</td><td>Profile blocks that range deliberately (reported as <i>skipped blocks</i>)</td><td>Read the block report; never assume a skipped block is zero</td></tr>
<tr><td>Session drops mid-read</td><td>TesterPresent stopped, adapter reset, ECU went to sleep</td><td>Check the session events; retry on a stable supply</td></tr>
</tbody></table>

<h3>Maps and XDFs</h3>
<table class="help-table"><thead><tr><th>Symptom</th><th>Likely cause</th><th>Fix</th></tr></tbody><tbody>
<tr><td>Table renders as noise</td><td>Endianness/cell size mismatch, or wrong definition</td><td>Try the correct software-version XDF; check byte order</td></tr>
<tr><td>Flag toggle changes other bits</td><td>You are looking at the raw byte, not the mask</td><td>Compare before/after raw values; only masked bits should move</td></tr>
<tr><td>Patch reports mismatch</td><td>The image is not the version the patch was authored for</td><td>Do not force it; find the matching definition or skip the patch</td></tr>
<tr><td>XDF refused on build</td><td>Uncatalogued definition, or the fitment check failed</td><td>Use the bundled definition for the family, or render without building</td></tr>
</tbody></table>

<h3>Builds, checksums and writes</h3>
<table class="help-table"><thead><tr><th>Symptom</th><th>Likely cause</th><th>Fix</th></tr></thead><tbody>
<tr><td>Build refuses: no checksum provider</td><td>XDF declares a checksum and no provider supports every title</td><td>Install/select a matching provider; do not seek an override</td></tr>
<tr><td>Build refuses: too many changes</td><td>More than 4096 changed bytes</td><td>Split the work or check the definition — a huge diff usually means a wrong XDF</td></tr>
<tr><td>Write refuses: no base map</td><td>No vaulted original, or its hash changed on disk</td><td>Complete a verified backup or attest an external one</td></tr>
<tr><td>Write refuses: hardware family</td><td>Image does not match the identified ECU</td><td>Use the image for this ECU; there is no override</td></tr>
<tr><td>Write refuses: writer locked</td><td>Family has an implemented but unverified writer</td><td>Unlock with the recovery acknowledgement, or use a verified path</td></tr>
<tr><td>Readback mismatch</td><td>Transfer corruption, wrong region, power problem</td><td>Treat as a failure; re-read before retrying</td></tr>
</tbody></table>

<h3>Evidence to collect</h3>
<p>Session log (Sessions → Events), the Link card details, the adapter pre-flight output, the image hash and the exact refusal text. With those, a problem is usually diagnosable in one message.</p>`,
    },
    {
      id: 'safety-blocked-capabilities', title: 'Why so much is blocked — and how to unblock it properly', category: 'safety',
      summary: 'The philosophy behind refused capabilities, what evidence would change a profile, and the contribution path that does not involve guessing.',
      tags: ['blocked', 'capability', 'evidence', 'contribution', 'research', 'policy'],
      related: ['ecu-confidence', 'protocol-evidence', 'safety-gates'],
      body: `
<h3>The rule</h3>
<p>Compatibility is not a protocol definition. A tool existing, a forum post saying it works, or a commercial product listing a model proves that <i>someone</i> can talk to the ECU. It does not publish the initialisation, framing, identifiers, scalings or the programming sequence. Guessing those from a sibling family is how ECUs get corrupted.</p>

<h3>So a capability stays blocked when</h3>
<ul>
  <li>the initialisation or framing is unpublished;</li>
  <li>an identifier table has no proven payload widths or scalings;</li>
  <li>memory geometry or the security exchange is unknown;</li>
  <li>a write sequence exists but has no proven recovery path.</li>
</ul>

<h3>How to unblock it</h3>
<ol>
  <li><b>Capture</b> the traffic on the exact model/ECU, with adapter, baud rate, key state and conditions recorded.</li>
  <li>Repeat it in a second independent session; note anything that differs.</li>
  <li>For memory, record the full geometry and a read verified by a second read.</li>
  <li>For programming, record session, security exchange, erase/transfer sequence and a successful recovery test.</li>
  <li>Contribute it with the raw bytes and a description — the project prefers evidence over confidence.</li>
</ol>

<h3>Simulated and offline paths stay open</h3>
<p>You can still practise everything: the simulator implements the full stack, offline tools accept user-supplied files, and the XDF library renders maps from any image you already have. Blocking hardware use does not block learning.</p>`,
    },
    {
      id: 'safety-legal', title: 'Legal, emissions and safety responsibilities', category: 'safety',
      summary: 'Emissions compliance, roadworthiness, warranty, customer consent and the limits of this project’s advice.',
      tags: ['legal', 'emissions', 'warranty', 'liability', 'customer', 'roadworthy', 'disclaimer'],
      related: ['safety-gates', 'safety-recovery'],
      body: `
<h3>Emissions</h3>
<p>On-road motorcycles are emissions-controlled. Changing fuel or ignition calibration, disabling closed-loop operation, altering evaporative or exhaust-device behaviour, or clearing fault memory to mask a fault can be illegal in your jurisdiction and can invalidate registration. This program does not tell you what is legal where you are.</p>

<h3>Roadworthiness and safety</h3>
<p>A calibration that increases torque or raises a rev limit can exceed the design margins of the clutch, gearbox, brakes or tyres. A change that alters idle stability or throttle response can matter more than a dyno number.</p>

<h3>Customer work</h3>
<ul>
  <li>Get written consent for any calibration change, including the bricking risk.</li>
  <li>Keep the original backup and deliver a copy to the customer.</li>
  <li>Record the before/after calibration hashes in the service report.</li>
  <li>Do not clear fault codes to hide a pre-existing fault.</li>
</ul>

<h3>Warranty and affiliation</h3>
<p>This project is not affiliated with Piaggio, Moto Guzzi, Harley-Davidson, Honda, Suzuki, Kawasaki, Yamaha, Triumph, Ducati, Dynojet or any tool vendor. Writing a calibration may void a manufacturer warranty. The software ships with no warranty; you accept responsibility for what you do with it.</p>

<h3>Equipment links</h3>
<p>The equipment guide contains Amazon affiliate links (tag <code>hardkore26-20</code>). They are search links, not inspected products or endorsements. No Amazon request is made by viewing the guide.</p>`,
    },
  ];

  window.GOB_HELP.topics = window.GOB_HELP.topics.concat(TOPICS);
}());

/* ======================================================================
 * GLOSSARY — term + plain-language definition. Each term is indexed
 * individually and deep-links to #help/glossary/<term>.
 * ==================================================================== */
(function () {
  'use strict';

  const GLOSSARY = [
    { term: 'Adaptation (self-learning)', definition: 'Values the ECU learns while running (idle trim, mixture adaptation). A reset discards them; the ECU relearns, so immediate behaviour changes are expected.', tags: ['reset', 'learning'] },
    { term: 'AFR (air–fuel ratio)', definition: 'Mass of air divided by mass of fuel. Petrol stoichiometry is about 14.7:1. Lower AFR = richer.', tags: ['fuel', 'wideband'] },
    { term: 'Actuator test', definition: 'Energising an output (injector, coil, pump, fan) deliberately to prove the circuit. IAW ECUs have no output timer, so the tool must end the pulse.', tags: ['service', 'output'] },
    { term: 'Base map', definition: 'The untouched calibration the motorcycle arrived with, vaulted with a SHA-256 and re-hashed before every write. The way back.', tags: ['backup', 'vault'] },
    { term: 'BDM / JTAG', definition: 'Direct processor debug interfaces used for bench recovery when an ECU no longer runs its bootloader.', tags: ['recovery', 'bench'] },
    { term: 'Bit flag', definition: 'A single setting stored in one bit of a byte, identified by an address and a mask. Changing it must preserve sibling bits.', tags: ['xdf', 'mask'] },
    { term: 'Bootloader', definition: 'The small program that can receive new firmware. On a 320 KiB 5AM full dump the first 0x4000 bytes are the bootloader prefix.', tags: ['flash', 'recovery'] },
    { term: 'Brick', definition: 'An ECU left unable to boot or communicate. Usually caused by an interrupted erase/write or a mismatched hardware family image.', tags: ['risk', 'recovery'] },
    { term: 'Calibration', definition: 'The data tables and constants inside the ECU that define how the engine is run. Distinct from the firmware code that reads them.', tags: ['tune', 'map'] },
    { term: 'CAN (Controller Area Network)', definition: 'Differential two-wire bus used by modern motorcycles, typically 500 kbit/s here, carrying broadcast and diagnostic traffic.', tags: ['bus', 'protocol'] },
    { term: 'Checksum', definition: 'A number computed from data to detect corruption. Frame, calibration and upload checksums are different mechanisms and are never interchangeable.', tags: ['integrity'] },
    { term: 'Closed loop', definition: 'The ECU trimming fuel based on the oxygen sensor to hold a target AFR. Interferes with wideband tuning measurements if left active.', tags: ['lambda', 'fuel'] },
    { term: 'Constant', definition: 'A single scalar calibration value (idle speed, rev limit, injector size), as opposed to a table.', tags: ['xdf'] },
    { term: 'DDFI', definition: 'Buell’s Digital Delphi Fuel Injection family, accessed over 5 V TTL serial — not K-Line, RS-232 or J1850.', tags: ['buell'] },
    { term: 'Delphi (Harley)', definition: 'The ECU family used on many Harley-Davidson models. CAN identity research here; J1850 VPW on older bikes.', tags: ['harley'] },
    { term: 'Derived value', definition: 'A number computed by the workstation from live channels (e.g. power from torque and RPM). Not an ECU reading; it inherits the worst confidence of its inputs.', tags: ['live'] },
    { term: 'DTC (diagnostic trouble code)', definition: 'A stored code describing a detected fault. Reading is low risk; clearing also discards freeze-frame and readiness data.', tags: ['faults'] },
    { term: 'ECU (engine control unit)', definition: 'The computer that runs the engine: reads sensors, drives injectors and ignition, stores faults and calibration.', tags: ['hardware'] },
    { term: 'EEPROM', definition: 'Electrically erasable memory inside the ECU, often holding adaptations or a small tune region distinct from flash.', tags: ['memory'] },
    { term: 'Endianness', definition: 'Byte order of a multi-byte value. Big-endian stores the most significant byte first; getting it wrong turns a table into noise.', tags: ['xdf', 'encoding'] },
    { term: 'Entropy (image check)', definition: 'A rough measure of randomness used in image validation: a calibration should be neither all 0xFF nor random noise.', tags: ['validation'] },
    { term: 'EPROM', definition: 'Socketed, UV-erasable memory used by older ECUs such as the IAW 16M. Read it with a programmer, keep the original chip.', tags: ['memory', '16m'] },
    { term: 'Fast init', definition: 'ISO 14230 initialisation: 300 ms idle, 25 ms K-Line low, release at 50 ms, then a validated StartCommunication reply.', tags: ['protocol'] },
    { term: 'Flash', definition: 'The main non-volatile program and calibration memory in a modern ECU; also the act of writing it.', tags: ['memory', 'write'] },
    { term: 'FTDI latency timer', definition: 'USB-serial buffering delay in the adapter driver. 16 ms is the default and makes long reads crawl; 1 ms is required for reliable flashing.', tags: ['adapter', 'driver'] },
    { term: 'Hardware family', definition: 'The ECU board revision (e.g. HW610). An image must match the identified family; mismatch is refused with no override.', tags: ['validation'] },
    { term: 'HD-LAN', definition: 'Harley-Davidson’s CAN bus. Observation is passive: the workstation listens to broadcast traffic and claims no write capability.', tags: ['harley', 'can'] },
    { term: 'Hex / hexadecimal', definition: 'Base-16 notation used for addresses, masks and byte values, written <code>0x4000</code>.', tags: ['notation'] },
    { term: 'IEEE-754', definition: 'The standard binary floating-point format. XDFs can declare 32- or 64-bit float cells.', tags: ['xdf', 'float'] },
    { term: 'ISO 9141-2', definition: 'OBD protocol over K-Line that shares the 5-baud physical initialisation with KWP2000 but uses keywords to select a different message protocol.', tags: ['protocol', 'obd'] },
    { term: 'ISO-TP (ISO 15765-2)', definition: 'Segmentation layer that carries long diagnostic messages over CAN using single, first, consecutive and flow-control frames.', tags: ['can', 'protocol'] },
    { term: 'J1850 VPW', definition: 'Older OBD bus (variable pulse width) used by some Harley-Davidson ECUs, reached through a VPW-capable ELM327.', tags: ['harley', 'protocol'] },
    { term: 'J2534', definition: 'Windows pass-thru API for vehicle communication devices. Presence of a vendor DLL does not implement a flashing sequence.', tags: ['adapter'] },
    { term: 'JetDrive', definition: 'Dynojet dyno telemetry over local UDP multicast. AFR/RPM/torque from the dyno, not from the motorcycle ECU.', tags: ['dyno', 'telemetry'] },
    { term: 'K-Line', definition: 'Single-wire 12 V diagnostic bus used by most motorcycles here; carries KWP2000, ISO 9141-2 or family dialects.', tags: ['bus'] },
    { term: 'KWP2000 (ISO 14230)', definition: 'Diagnostic protocol defining fast and 5-baud initialisation, sessions, services and per-frame checksums. The 5AM and 7SM use it.', tags: ['protocol'] },
    { term: 'Lambda', definition: 'Normalised AFR: 1.0 = stoichiometric. This program works in AFR and performs no lambda conversion.', tags: ['fuel'] },
    { term: 'Latency (adapter)', definition: 'Round-trip time for a byte through the interface. Measured by the adapter pre-flight card.', tags: ['adapter'] },
    { term: 'Map', definition: 'A table of calibration values indexed by operating point (RPM and load), e.g. fuel or ignition.', tags: ['tuning'] },
    { term: 'Mask', definition: 'A bit pattern selecting which bits of a byte a flag or field occupies.', tags: ['bit'] },
    { term: 'MSE6', definition: 'Bosch ECU family used on some CFMoto models; only an offline checksum-record heuristic is provided here.', tags: ['cfmoto'] },
    { term: 'NRC (negative response code)', definition: 'The code an ECU returns to refuse a request (e.g. 0x22 conditions not correct). Shown in the link/session details.', tags: ['protocol'] },
    { term: 'Open loop', definition: 'Fuel delivered from tables without oxygen-sensor feedback. Required for wideband tuning measurements.', tags: ['fuel'] },
    { term: 'Optimistic lock (expected value)', definition: 'A staged change records the raw value it expects to find. If the image differs at build time, the change is refused rather than applied blindly.', tags: ['xdf', 'safety'] },
    { term: 'Patch (XDF)', definition: 'A defined set of byte spans applied as a unit, with expected base bytes so a wrong software version is detected.', tags: ['xdf'] },
    { term: 'PCAN', definition: 'PEAK-System’s CAN interface family; supported through its vendor driver.', tags: ['adapter', 'can'] },
    { term: 'PIDs (OBD)', definition: 'Parameter IDs for standard OBD live data, requested by number; only the PIDs a profile declares are used.', tags: ['obd'] },
    { term: 'PGM-FI', definition: 'Honda’s Keihin-based fuel injection system and its K-Line diagnostic dialect.', tags: ['honda'] },
    { term: 'Plausibility check', definition: 'A heuristic opinion about live values, naming the numbers behind it. Never a diagnosis.', tags: ['live'] },
    { term: 'Programming session', definition: 'The ECU state that permits memory writes. Entered explicitly, held exclusively, and exited after the operation.', tags: ['write'] },
    { term: 'Provenance', definition: 'Where a tune’s numbers came from: operator, dyno, AFR log or an external package. Recorded with every build and labelled “not endorsed”.', tags: ['tune', 'build'] },
    { term: 'Pulse width', definition: 'Injector open time, the primary fuel-delivery quantity on a port-injected engine.', tags: ['fuel'] },
    { term: 'PVV', definition: 'Dynojet Power Vision calibration XML format; edited here offline only.', tags: ['harley', 'power vision'] },
    { term: 'Raw value', definition: 'The bytes as stored in the ECU, before any conversion equation is applied.', tags: ['xdf'] },
    { term: 'Readback verification', definition: 'Re-reading a region after a write and comparing it to the transmitted image. A write without readback is unverified.', tags: ['write'] },
    { term: 'Region', definition: 'A named address range in ECU memory (flash, eeprom) with a start, size, block size and writability flag.', tags: ['memory'] },
    { term: 'RLI sweep', definition: 'A read-only sweep of local identifiers using service 21, offered only where that range is established non-mutating.', tags: ['discovery'] },
    { term: 'ROM', definition: 'Read-only memory holding program and calibration; used loosely for the whole ECU image.', tags: ['memory'] },
    { term: 'rusEFI', definition: 'Open-source aftermarket engine controller with a serial console and INI-defined calibration pages.', tags: ['aftermarket'] },
    { term: 'Seed / key', definition: 'Challenge-response unlocking protected services: the ECU sends a random seed and expects a computed key. Wrong keys can lock the service.', tags: ['security'] },
    { term: 'SLCAN', definition: 'ASCII serial protocol for CAN adapters (Lawicel style).', tags: ['can', 'adapter'] },
    { term: 'SocketCAN', definition: 'Linux kernel CAN interface (<code>can0</code>) configured outside the application with <code>ip link</code>.', tags: ['can', 'linux'] },
    { term: 'Stoichiometric', definition: 'The chemically ideal air–fuel ratio; about 14.7:1 for petrol.', tags: ['fuel'] },
    { term: 'Stride', definition: 'Distance in bytes between successive rows (or columns, for column-major layouts) of a table.', tags: ['xdf'] },
    { term: 'Table (XDF)', definition: 'A 1D or 2D calibration array with axes, a conversion equation and a storage address.', tags: ['xdf'] },
    { term: 'THAT(...)', definition: 'XDF function that reads another table at computed coordinates; used for load-dependent limits and corrections.', tags: ['xdf', 'math'] },
    { term: 'TesterPresent', definition: 'Keep-alive message that stops the ECU dropping an idle diagnostic session. Typically every 2 s.', tags: ['protocol'] },
    { term: 'Token (confirmation)', definition: 'A single-use, content-locked authorisation for one risky operation. Any material change invalidates it.', tags: ['safety'] },
    { term: 'TPS', definition: 'Throttle position sensor. On older open-loop Guzzis it is set mechanically with a voltmeter.', tags: ['sensor'] },
    { term: 'Tune', definition: 'A complete calibration image or the change set that produces one.', tags: ['tuning'] },
    { term: 'UDS (ISO 14229)', definition: 'Unified diagnostic services; modern service set often carried over ISO-TP on CAN.', tags: ['protocol'] },
    { term: 'VE (volumetric efficiency)', definition: 'How completely a cylinder fills, expressed as a percentage; the basis of speed-density fuel tables.', tags: ['tuning'] },
    { term: 'Vault (base map)', definition: 'The protected store holding the original calibration with its hash, separate from ordinary files.', tags: ['backup'] },
    { term: 'Wideband', definition: 'A broadband oxygen sensor and controller that reports actual AFR across a wide range, required for tuning.', tags: ['fuel', 'dyno'] },
    { term: 'XDF', definition: 'TunerPro definition file describing addresses, axes, equations, flags and patches for a calibration image.', tags: ['tuning'] },
    { term: 'ZDL', definition: 'Zeitronix data-logger CSV export, convertible to LogWorks DIF by the workshop tool.', tags: ['wideband'] },
  ];

  window.GOB_HELP.glossary = GLOSSARY;
}());

/* ======================================================================
 * ECU family notes — extra prose shown on generated #help/ecu/<id> pages.
 * Everything else comes from the live catalog.
 * ==================================================================== */
(function () {
  'use strict';

  window.GOB_HELP.ecuNotes = {
    '5am': 'Capture-verified Marelli controller fitted to every CARC-framed Guzzi. See <a href="#help/ecu-5am">the 5AM deep dive</a> for parameter coverage, 19-block geometry and the gated write path.',
    '16m': 'Legacy pre-KWP protocol at 1,200/7,680 baud. Temperatures stay as raw counts because sources disagree on the offset. Maps live in a socketed EPROM; use a programmer.',
    '7sm': 'Fast-init K-Line session with a published diagnostic log. Identification and baud switch only — no validated memory geometry.',
    '11mp': 'Euro 5 CAN controller. No published identifier pair, DID table or routine IDs, so physical sessions are refused before any request is sent.',
    'miug3': 'OEM material names the identifiers but not the framing or scaling. Closed tools implement it; compatibility is not a publishable definition.',
    'harley_delphi_can_uds': '500 kbit/s, 0x7E0/0x7E8 identity research. Authentication differences may prevent replies; see <a href="#help/ecu-harley-family">Harley paths</a>.',
    'harley_j1850_harleydroid': 'J1850 VPW read-only research through a VPW-capable ELM327. No memory access.',
    'honda_pgmfi_research': 'Keihin PGM-FI K-Line identification and live data. Pair it with the offline decoder and the Honda checksum tools.',
    'generic_obd_can_11bit': 'Standard OBD-II requests over 11-bit CAN, opt-in. Live PIDs and stored DTCs only — no memory, no programming.',
    'generic_obd_iso9141_kline': 'Standard OBD-II over ISO 9141-2 K-Line (5-baud init, key bytes 08 08 / 94 94), opt-in. Live PIDs and stored DTCs only — no memory, no programming.',
    'generic_kwp2000_kline': 'Standard KWP2000 (ISO 14230) read-only over K-Line (fast or 5-baud init), opt-in. Identification, local-identifier reads and stored DTCs only — every mutating service is refused.',
    'generic_uds_can_11bit': 'Standard UDS (ISO 14229) read-only over 11-bit CAN at 500 kbit/s, opt-in. Session control, ReadDataByIdentifier, ReadDTCInformation and TesterPresent only — no writes, clears, routines or programming.',
    'suzuki_sds_gsxr_research': 'A raw SDS request/response snapshot from separate sources. Candidates only; no identity, faults or memory.',
    'triumph_bonneville_865_2009': 'ISO 9141-2 OBD read-only. SAE gauge formulas, not dash-verified. No clears, memory or tuning.',
  };
}());
