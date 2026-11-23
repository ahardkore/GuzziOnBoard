# HTTP API reference

Every route the local server (or the desktop shell, which serves the same
API) answers. The route table lives in `guzzionboard/server.py`; this page
is generated from it and `tests/test_api_reference.py` fails when the two
drift.

The hosted browser demo answers a subset of these from `web/demo-api.js`
and `web/demo-lab.js` and explicitly refuses the rest; `tests/
test_demo_mode.py` fails if a route is in neither. A refusal is HTTP 501
with `code: demo_local_only`, never a fake success.

## Conventions

* Base URL: `http://127.0.0.1:8000` (console) or the desktop shell's port.
  The console server binds loopback only; a wider bind is an explicit
  `--host`, and it is warned about because any client on the network can
  then call the API directly.
* `GET` routes take query parameters; `POST` routes take one JSON object.
  `Content-Length` is required, must be numeric, must not exceed 16 MiB, and
  a body containing `NaN`/`Infinity` is refused.
* Every answer is a JSON object. Failures carry `error` and `code`:
  `bad_request` (400), `safety`/`token`/`refused` (403), `not_connected`/
  `programming` (409), `no_driver`/`no_key_provider` (501), `transport`/
  `protocol` (502), `internal` (500, with no internal detail echoed).
* The desktop shell requires `X-GuzziOnBoard-Token` on every `/api/*` call;
  the console server has no token and relies on the loopback bind plus the
  origin check.
* A page from another origin cannot call the API: `Origin` is compared with
  the `Host` the request addressed (and the loopback aliases), and a
  malformed `Origin` is a refusal, not an error.

## Read routes (GET)

| Route | Handler | What it answers |
| --- | --- | --- |
| `GET /api/catalog` | `get_catalog` | answers `summary`, `makes`, `models`, `vehicles`, `ecus`, `model`, `variants`, `make`, … |
| `GET /api/catalog/resolve` | `get_resolve` | answers `model`, `make`, `year`, `ambiguous`, `matches`, `ecu_detail` |
| `GET /api/status` | `get_status` | — |
| `GET /api/identify` | `get_identify` | — |
| `GET /api/live` | `get_live` | answers `at`, `samples`, `derived`, `findings`, `analysis_note` |
| `GET /api/derived` | `get_derived_catalog` | answers `channels`, `key`, `name`, `unit`, `group`, `sources`, `note`, `delta` |
| `GET /api/sim` | `get_sim` | answers `available`, `transport`, `faults`, `reason` |
| `GET /api/parameters` | `get_parameters` | answers `parameters`, `error` |
| `GET /api/dtcs` | `get_dtcs` | answers `context_note`, `clear` |
| `GET /api/actuators` | `get_actuators` | answers `actuators`, `active`, `decision` |
| `GET /api/routines` | `get_routines` | answers `routines`, `decision` |
| `GET /api/sessions` | `get_sessions` | answers `sessions` |
| `GET /api/sessions/events` | `get_session_events` | answers `name`, `total`, `events`, `error` |
| `GET /api/sessions/replay` | `get_session_replay` | Scrubbable snapshots, with derived values and findings redone.; answers `error` |
| `GET /api/procedures` | `get_procedures` | answers `procedures`, `run`, `note` |
| `GET /api/report` | `get_report` | answers `report`, `temp_unit`, `text` |
| `GET /api/maps` | `get_maps` | answers `directory`, `bundled_directory`, `xdfs`, `groups`, `vehicle`, `base_map`, `build`, `make`, … |
| `GET /api/maps/library` | `get_map_library` | Table-level index of the bundled definitions, for the library finder. |
| `GET /api/checksum-providers` | `get_checksum_providers` | answers `directory`, `providers`, `errors`, `note` |
| `GET /api/recommendations` | `get_recommendation_packages` | answers `directory`, `packages`, `errors`, `bundled`, `note` |
| `GET /api/physical-validation` | `get_physical_validation` | answers `directory`, `records`, `errors`, `physically_validated`, `complete_evidence_records`, `note` |
| `GET /api/protocol-updates` | `get_protocol_updates` | answers `ecu`, `family`, `confidence`, `capabilities`, `effective_capabilities`, `physical_supported`, `field_confirmation`, `path`, … |
| `GET /api/memory` | `get_memory` | answers `base_map`, `capabilities`, `job`, `checkpoints`, `acknowledgement`, `programming_enabled`, `unverified_keys_accepted`, `unverified_hardware_writes_enabled`, … |
| `GET /api/memory/progress` | `get_memory_progress` | — |
| `GET /api/memory/basemap` | `get_basemap` | answers `base_map`, `restore`, `vault`, `directory` |
| `GET /api/security` | `get_security` | answers `providers`, `plugin_dir`, `unverified_keys_accepted` |
| `GET /api/adapter` | `get_adapter` | answers `report`, `text`, `ports` |
| `GET /api/adapter/j2534` | `get_j2534` | — |
| `GET /api/tools/gearing` | `get_gearing` | answers `final_drive`, `tyre`, `primary` |
| `GET /api/sessions/export` | `get_export` | A recorded session as CSV or JSON.; answers `format`, `name`, `filename`, `rows`, `content`, `csv`, `note`, `error` |
| `GET /api/desktop` | `get_desktop` | answers `available`, `reason` |
| `GET /api/desktop/ping` | `get_desktop_ping` | Cheap liveness probe, used to recognise our own earlier launch.; answers `ok`, `app`, `version`, `desktop` |
| `GET /api/preferences` | `get_preferences` | — |
| `GET /api/preferences/browse` | `get_preferences_browse` | — |

## Action routes (POST)

These change state: a session, a connection, a file, a stored record.
Each is gated by the safety layer described in
[Programming](PROGRAMMING.md) and [Architecture](ARCHITECTURE.md); a
403 with `code: safety` carries the decision that refused it.

| Route | Handler | What it answers |
| --- | --- | --- |
| `POST /api/select` | `post_select` | answers `error` |
| `POST /api/connect` | `post_connect` | — |
| `POST /api/disconnect` | `post_disconnect` | — |
| `POST /api/checklist` | `post_checklist` | — |
| `POST /api/dtcs/clear` | `post_dtcs_clear` | — |
| `POST /api/actuators/pulse` | `post_actuator_pulse` | — |
| `POST /api/actuators/release` | `post_actuator_release` | — |
| `POST /api/routines/run` | `post_routine_run` | — |
| `POST /api/discover` | `post_discover` | — |
| `POST /api/memory/backup` | `post_memory_backup` | — |
| `POST /api/memory/attest-backup` | `post_memory_attest_backup` | answers `error` |
| `POST /api/memory/basemap` | `post_basemap_save` | File an image that is already on disk as this ECU's base map.; answers `base_map`, `result`, `error` |
| `POST /api/memory/basemap/restore` | `post_basemap_restore` | The plan for putting the base map back.; answers `restore`, `error`, `base_map` |
| `POST /api/memory/read` | `post_memory_read` | answers `path`, `describe`, `research_only` |
| `POST /api/memory/validate` | `post_memory_validate` | answers `error` |
| `POST /api/memory/write` | `post_memory_write` | answers `error` |
| `POST /api/memory/check-write` | `post_memory_check_write` | answers `error` |
| `POST /api/maps/render` | `post_maps_render` | answers `image`, `source`, `error`, `path`, `sha256`, `is_base_map`, `base_map` |
| `POST /api/maps/diff` | `post_maps_diff` | answers `image`, `error` |
| `POST /api/maps/validate-definition` | `post_maps_validate_definition` | answers `declared`, `compatible_providers`, `plugin_errors`, `selection_required`, `error` |
| `POST /api/maps/analyze-log` | `post_maps_analyze_log` | Overlay an offline log and propose bounded, non-writing fuel edits.; answers `error` |
| `POST /api/maps/preview` | `post_maps_preview` | Quantize and diff staged edits without writing a file.; answers `diff`, `writes_file`, `error` |
| `POST /api/maps/research-preview` | `post_maps_research_preview` | Preview user-supplied XDF edits without creating an image or certifying fitment.; answers `research_only`, `writes_file`, `source`, `xdf`, `address_base`, `changes`, `diff`, `candidate_sha256`, … |
| `POST /api/maps/harley-research-export` | `post_maps_harley_research_export` | Export using the one source-described Delphi layout. |
| `POST /api/maps/research-export` | `post_maps_research_export` | Export within an operator-declared file range, without ECU access. |
| `POST /api/maps/build` | `post_maps_build` | Create a new, provenance-carrying image from explicit XDF edits.; answers `error`, `source_sha256`, `output_sha256`, `output_path`, `xdf`, `changes`, `base_map_source`, `recommendation`, … |
| `POST /api/recommendations/validate` | `post_recommendation_validate` | answers `valid`, `package`, `error` |
| `POST /api/physical-validation/validate` | `post_physical_validation_validate` | answers `valid`, `record`, `error` |
| `POST /api/protocol-updates/check` | `post_protocol_updates_check` | Fetch a pack and describe exactly what applying it would change.; answers `ok`, `url`, `preview`, `envelope`, `note` |
| `POST /api/protocol-updates/apply` | `post_protocol_updates_apply` | Apply the exact bytes the caller previewed. |
| `POST /api/protocol-updates/revert` | `post_protocol_updates_revert` | — |
| `POST /api/protocol-updates/pin-key` | `post_protocol_updates_pin_key` | — |
| `POST /api/protocol-updates/unpin-key` | `post_protocol_updates_unpin_key` | — |
| `POST /api/confirmations/build` | `post_confirmations_build` | Freeze this session into a bundle the operator can submit.; answers `bundle`, `stored`, `submission`, `note`, `id`, `claims`, `capture_sha256` |
| `POST /api/confirmations/verify` | `post_confirmations_verify` | Recompute a bundle's claims from the capture it names.; answers `ok`, `bundle_path`, `report` |
| `POST /api/confirmations/validate` | `post_confirmations_validate` | answers `ok`, `bundle` |
| `POST /api/programming/enable` | `post_programming_enable` | answers `programming_enabled`, `unverified_keys_accepted`, `unverified_hardware_writes_enabled` |
| `POST /api/programming/disable` | `post_programming_disable` | answers `programming_enabled`, `unverified_hardware_writes_enabled` |
| `POST /api/programming/unlock-writer` | `post_programming_unlock_writer` | answers `unverified_hardware_writes_enabled`, `unverified_keys_accepted` |
| `POST /api/programming/lock-writer` | `post_programming_lock_writer` | answers `unverified_hardware_writes_enabled` |
| `POST /api/security/unverified` | `post_security_unverified` | The operator's explicit, audited, session-scoped acceptance of key; answers `allow_unverified_keys`, `note` |
| `POST /api/adapter/latency` | `post_adapter_latency` | answers `ok`, `latency_ms`, `instructions` |
| `POST /api/tools/canlog` | `post_tools_canlog` | Analyse a passively sniffed CAN capture: which ids are the pair?; answers `error` |
| `POST /api/tools/harley-hdlan-listen` | `post_tools_harley_hdlan_listen` | Explicit, bounded SocketCAN receive; never submits a CAN frame.; answers `error` |
| `POST /api/tools/jetdrive` | `post_tools_jetdrive` | Observe a bounded local Dynojet multicast window, optionally request metadata.; answers `error` |
| `POST /api/tools/bikestudio` | `post_tools_bikestudio` | Fetch one explicitly requested public source page, never a caller URL.; answers `error` |
| `POST /api/tools/buell-ddfi` | `post_tools_buell_ddfi` | Explicit TTL serial Buell version, runtime or bounded EEPROM GET.; answers `error`, `token`, `expires_seconds`, `read_token`, `original_path`, `original_verified`, `map_xdf` |
| `POST /api/tools/harley-memory` | `post_tools_harley_memory` | Explicit opt-in source-scoped Delphi memory research, local only.; answers `error`, `token`, `expires_seconds` |
| `POST /api/tools/rusefi-read` | `post_tools_rusefi_read` | Explicit aftermarket rusEFI reads and separately reviewed calibration burn.; answers `error`, `token`, `expires_seconds` |
| `POST /api/tools/yamaha-mt03-listen` | `post_tools_yamaha_mt03_listen` | Receive one bounded Yamaha dashboard stream window; send no request.; answers `error` |
| `POST /api/tools/klinelog` | `post_tools_klinelog` | Characterise a K-Line capture: which local identifiers answered?; answers `error` |
| `POST /api/tools/z2dif` | `post_tools_z2dif` | Convert a Zeitronix ZT-2 (ZDL) CSV log to LogWorks DIF.; answers `error` |
| `POST /api/tools/rpmsignal` | `post_tools_rpmsignal` | Render a bench RPM trigger signal to a WAV file.; answers `error`, `presets` |
| `POST /api/sessions/compare` | `post_sessions_compare` | answers `error` |
| `POST /api/sim/engine` | `post_sim_engine` | answers `error` |
| `POST /api/sim/faults` | `post_sim_faults` | answers `error` |
| `POST /api/sim/comms` | `post_sim_comms` | answers `error` |
| `POST /api/procedures/start` | `post_procedure_start` | answers `key`, `name`, `run`, `error` |
| `POST /api/procedures/advance` | `post_procedure_advance` | answers `run`, `error`, `key`, `status`, `verdict` |
| `POST /api/procedures/abort` | `post_procedure_abort` | answers `run`, `error` |
| `POST /api/desktop/raise` | `post_desktop_raise` | answers `ok`, `reason` |
| `POST /api/desktop/save` | `post_desktop_save` | — |
| `POST /api/desktop/save-binary` | `post_desktop_save_binary` | — |
| `POST /api/desktop/print` | `post_desktop_print` | — |
| `POST /api/desktop/open-external` | `post_desktop_open_external` | — |
| `POST /api/desktop/open-folder` | `post_desktop_open_folder` | — |
| `POST /api/desktop/quit` | `post_desktop_quit` | — |
| `POST /api/preferences` | `post_preferences` | — |
| `POST /api/preferences/save-file` | `post_preferences_save_file` | — |

## Not part of the API

`/`, `/index.html`, `/app.js` and the other static assets are served from
`web/`; `/desktop-bridge.js` is injected only into a desktop-served page.
The read-sharing relay (`guzzionboard/validation_service.py`) and the
Cloudflare Worker are separate services with their own two endpoints
(`POST /v1/confirmations`, `GET /protocol-update.json`); they never proxy
this API.

