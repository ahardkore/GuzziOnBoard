# Physical ECU and dyno validation protocol

## Status

**No real-ECU or dyno validation evidence is bundled with this repository.** The
software test suite, simulator, and hosted demo do not substitute for a physical
ECU, motorcycle, calibrated dynamometer, wideband instrumentation, qualified
operator, or independent review. A claim is not upgraded merely because a JSON
manifest says `pass`.

The machine-readable evidence format is
[`schemas/physical-validation.schema.json`](schemas/physical-validation.schema.json).
Completed records and every referenced artifact must be retained outside Git
unless they are small, redistributable, and intentionally contributed. Relative
artifact paths are resolved from the manifest's directory, and locally present
artifacts must match their recorded SHA-256 before the registry calls that
evidence index complete.

## Stop conditions

Stop immediately for unstable power, communication loss, unexpected ECU
identity, non-matching hardware/software, checksum refusal, failed read-back,
knock, detonation, lean excursions, excessive temperature, fluid leaks,
abnormal noise, tire/driveline concerns, inadequate ventilation, or loss of
qualified supervision. Do not use public roads for calibration validation.

## A. Bench protocol for each supported ECU/software combination

1. **Independent setup review**
   - Record ECU family, hardware, software, serial (redacted if published),
     adapter, harness, power-supply model/current limit, and application version.
   - Photograph connections and record ambient conditions.
   - Confirm the XDF filename and SHA-256 against the exact software version.
2. **Immutable acquisition**
   - Read the applicable region twice in separate sessions.
   - Require byte-for-byte agreement; record both session logs and hashes.
   - File the first agreed image as the protected base map.
3. **Read-only definition validation**
   - Run structural validation with the image.
   - Review every fatal/warning finding and representative table values/axes.
   - Compare named addresses/scalings against an independent, documented tool.
4. **Minimal reversible edit**
   - Use a documented, safe, observable calibration field approved by the test
     owner; do not invent a fuel/spark value merely to exercise writing.
   - Attach evidence, preview exact quantization, and record plan/source/XDF hashes.
   - Where the XDF declares checksums, use only an explicitly selected provider
     whose algorithm and test vectors are documented. Retain plugin SHA-256.
5. **Program and read back**
   - Follow ECU-specific power/recovery requirements and maintain stable supply.
   - Capture all protocol traffic. Read back the full writable region after reset.
   - Require the read-back to equal the reviewed output byte-for-byte, allowing
     only separately documented ECU-managed bytes.
6. **Restore and repeat**
   - Restore the protected base map and perform another full read-back.
   - Repeat edit/program/read-back/restore at least three times per ECU/software
     combination and with each supported adapter/transport configuration.
7. **Fault/recovery matrix**
   - Under a controlled sacrificial/recoverable bench setup only, test failures
     at documented safe interruption points: request refusal, transfer timeout,
     bad block acknowledgement, application restart, and operator abort.
   - Never improvise power interruption tests on an ECU without a proven recovery
     path, boot-mode equipment, and explicit test authorization.

Required evidence includes session captures, source/output/read-back hashes,
photos, equipment records, observed ECU responses, check results, and operator
identity. A successful simulator run is recorded separately and never marked as
real-ECU evidence.

## B. Motorcycle and dyno protocol for each calibration/configuration

1. **Qualified facility and baseline**
   - Use an experienced motorcycle dyno operator, restraints, cooling airflow,
     exhaust extraction, fire protection, and a current dyno calibration record.
   - Record motorcycle model/year, engine, intake, exhaust, fuel, sensors,
     gearing, tires, ambient conditions, dyno serial, weather station, and
     correction standard.
   - Complete mechanical inspection and establish repeatable protected-base runs.
2. **Instrumentation validation**
   - Use a calibrated wideband independent of the narrowband ECU sensor.
   - Verify sample timestamps, transport delay, RPM/load alignment, and units.
   - Inspect for exhaust leaks and sensor faults before using AFR data.
3. **Controlled change review**
   - Confirm exact source/XDF/plan/output hashes and configuration-specific
     recommendation evidence. Review all checksum-provider details.
   - Define abort limits for AFR/lambda, knock, temperature, pressure, power,
     wheel speed, and operator-observed behavior before the run.
4. **Steady-state cells before sweeps**
   - Collect enough settled samples per cell with closed-loop/transient states
     identified. Do not treat acceleration enrichment or sensor lag as steady data.
   - Generate bounded review-only proposals; independently review each proposal.
   - Build only through the normal preview/evidence/liability flow.
5. **Repeatability and comparison**
   - Use multiple warmed baseline and candidate runs in alternating order.
   - Retain raw, un-smoothed run files. Report variance, not just the best run.
   - Validate part throttle, transitions, hot restart, idle, and safe thermal
     behavior, not only full-throttle peak power.
6. **Post-test verification**
   - Read back and hash the ECU image, scan faults, inspect the motorcycle, and
     return to the protected base map when the test plan requires it.
   - Mark any failed, aborted, or incomplete check in the manifest; never delete
     an unfavorable run from the evidence set.

## C. Coverage and release decision

Maintain a matrix by motorcycle, ECU hardware/software, XDF SHA-256, checksum
provider SHA-256, transport/adapter, operating system, and calibration package.
For a combination to be called physically validated, its evidence set needs:

- repeated base-map reads and restores;
- repeated exact output read-backs;
- documented checksum acceptance where applicable;
- complete communication captures;
- dyno repeatability, raw AFR/log data, and facility calibration evidence for
  any performance or fueling claim;
- no failed or incomplete safety-critical check;
- review by someone other than the operator who created the calibration.

Until those artifacts exist, UI and documentation must say **not physically
validated**, regardless of unit-test coverage.
