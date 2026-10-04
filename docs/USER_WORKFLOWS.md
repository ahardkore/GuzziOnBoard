# Guided user workflows

This document translates the supplied beginner tutorial for GuzziDiag into GuzziOnBoard product flows. Reference: [GuzziDiag HowTo - A tutorial for beginners](https://www.thisoldtractor.com/moto_guzzi_quota_guzzidiag_howto_-_a_tutorial_for_beginners.html).

The key improvement is to replace several standalone utilities and hidden sequencing rules with one guided session. The user should not need to know which legacy reader, writer, or actor command to launch.

## Connect

1. Choose motorcycle and ECU family, or select **Detect**.
2. Show available serial adapters with chip/driver details and port ownership.
3. Run an adapter self-test before touching the ECU.
4. Show a visual connection checklist: diagnostic connector, battery clips, USB adapter, ignition state.
5. Ask for ignition-on only when the transport is ready; never ask the user to start the engine during identification.
6. Display ECU identity and save it to the session.

The UI should explain that the diagnostic port, adapter, and ECU are separate pieces. It should never present a bare COM port as if it were a motorcycle identity.

## Live data

The reference uses eight selectable readouts. GuzziOnBoard should provide:

- curated dashboard presets for each ECU family;
- searchable values with descriptions, units, and expected ranges;
- a custom dashboard saved per motorcycle;
- a chart toggle and CSV/session logging;
- a clear distinction between raw ECU values and calculated/derived values.

## Backup before change

A **Create verified backup** action should be available before any service or map operation. It must show estimated duration, prevent computer sleep, retain the raw file, calculate a hash, and require the user to confirm that the backup can be reopened. Long operations need pause/resume behavior or a clear recovery path—not a generic spinner.

## Map writing

Map writing should be a guided workflow, not an enabled button in the normal dashboard. It should include compatibility validation, stable-power checks, exclusive adapter ownership, typed confirmation, progress, post-write verification, and ignition-off timing. See `7SM_WORKFLOW.md` for 7SM-specific rules.

## TPS reset and actor operations

The tutorial highlights that a TPS reset is performed with the engine stopped, from an Actors screen, and then verified in Measurements. GuzziOnBoard should model this as:

1. Preconditions card: engine stopped, ignition on, stable voltage, correct ECU.
2. One explicit **Reset TPS** action.
3. Confirmation response and settling timer.
4. Automatic return to the TPS measurement with before/after values.
5. Session log entry and report note.

Other actor tests should use the same precondition/action/result pattern. The UI must identify actions that operate relays, injectors, ignition, or the fuel pump and include a stop control where applicable.

## CO trim

CO trim is an engine-running operation and must not be grouped with engine-off learning. The guided flow should require a minimum coolant temperature, show the current value and permitted range, prompt for engine-running state, and log every adjustment. It should suggest making small changes and provide a clear finish/revert action.

## Beginner mode and expert mode

- **Beginner mode:** guided steps, explanations, safety checks, recommended dashboards, and plain-language results.
- **Expert mode:** raw frames, selectable polling, actor commands, protocol timing, and exportable logs.

Both modes must use the same safety gate and audit trail. Expert mode must not bypass power, compatibility, or backup requirements.
