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

## Practising on the simulated motorcycle

The simulator is not only a development convenience; it is where somebody
learns to read the data before they touch a bike. The **Simulated bike** view
drives it directly and exists only while the transport in use is the simulator
or the virtual CAN bus — the endpoints behind it refuse otherwise, so there is
no path from these controls to a K-Line.

What it offers:

- **Engine controls** — ignition, throttle, ambient temperature, battery
  condition, in-gear road speed, and a fast-forward for the thermal model so a
  warm-up does not have to be waited out in real time.
- **Seeded faults** — a railed head sensor (both rails), a dead TPS, a lazy
  lambda sensor, a failed charging system, an air leak, a jammed idle stepper,
  a partially blocked front injector and a rear-cylinder misfire. Each one
  changes the physics first and stores its code later.
- **Comms quality** — dropped requests, corrupt checksums, `responsePending`
  and extra latency, because a marginal adapter is part of the job.

And because the simulator speaks the real wire protocol, *every other view
works against it too* — identify, live data and findings, fault memory,
service adaptations, actuator tests, guided tests, discovery sweeps, session
recording and replay, and the complete ECU-memory flow in the ECU memory view:
backup, validate, and the whole gated flash cycle up to a read-back-verified
write. Nothing is a special case: the UI simply calls the same endpoints, and
the workstation, knowing the session is simulated, presents the capability set
the simulator has demonstrably proven — clearly labelled *simulated*, so there
is never an implication that real hardware would behave with the same freedom.

The maturation behaviour is deliberate and worth teaching from:

1. Seed a fault and watch the **live data** move — the derived channels and
   the plausibility checks react long before anything is in fault memory.
2. Read the fault memory: the code arrives as *pending* first, then
   *confirmed*.
3. Clear it with the cause still present and read again — it comes back, after
   the same delay it took the first time. Clearing a code is not a repair.
4. Remove the cause and read again — the stored code is still there until it
   is erased, which is how fault memory actually works.

Two of the faults (air leak, jammed stepper) store the same code, `P0505`, and
are told apart only by the live data: both raise the idle error, but the air
leak drives the stepper *closed* while the jammed stepper does not move at all.
That pair is the best single demonstration of why this workstation shows
channels rather than just codes.

## Getting the data out, and putting it back in

A session that cannot leave the tool is of limited use to anybody.

- **Export CSV** (Sessions view, or the Live view for whatever is on screen)
  writes one row per polling sweep. The first row names the channels, the
  second carries their units, and the raw bytes travel in their own columns —
  so the spreadsheet still carries its provenance and a wrong scaling can be
  recomputed from the file rather than re-measured on the bike.
- **Replay** scrubs back through a recorded session. The derived channels and
  the plausibility checks are recomputed at each point, from the bytes that
  were recorded then, with the *recorded* timestamps driving the sixty-second
  window — so what you see on replay is what you would have seen live.

## Workshop utilities that need no ECU

The **Tools** view collects the helpers that inherit the job of the old
GuzziDiag-era utility apps. They run offline — nothing here touches the
motorcycle:

- **Gearing & road speed.** Pick the bike from the presets (the ratio table
  read out of the mirrored GearSpeed app — sixty-odd models, Guzzis included),
  set the rear tyre and the bevel-box final drive, and it tabulates the road
  speed each gear gives you up the rev range. Rows above the preset's red
  line are dimmed. Type ratios in the *Gears* field to try a gearbox the
  table does not know.
- **Wideband log converter.** Paste the CSV a Zeitronix ZDL logger exports
  and it comes back as the DIF table LogWorks and Excel import — with the
  reference converter's admitted times-four timeline error *fixed*. The
  *reference behaviour* toggle exists only for byte-for-byte comparisons
  with the old tool; the download button saves the result.
- **Bench RPM trigger signal.** Makes an unmounted ECU believe the engine
  turns: it renders a trigger-wheel pattern (the geometries are transcribed
  from RPMSensorEmu's own config files — 46 teeth plus two missing on the
  Guzzi camshaft wheel) as a WAV you play through an AC-coupled buffer into
  the sensor input. A batch line like `5000|1000|3000` ramps from one engine
  speed to another, exactly like the reference tool's `.rbt` programs. An
  ECU that believes the engine turns can energise coils and injectors —
  unplug what you do not want live.

Each tool carries a note at the top describing what it does and where its
numbers come from.

## Guided tests

The Guided tests view runs multi-step procedures rather than single pulses.
Each one is: put the bike in a known state, do one bounded thing, watch the
right channels, say what it means.

Shipped procedures: idle health check, charging system check, fuel pump prime
and pressure decay, injector circuit test, cold-start sensor plausibility.

Rules the runner follows:

1. A procedure is only offered when the catalog says this ECU family has the
   channels and actuators it needs — the list shows exactly what is missing
   otherwise.
2. Observations are ordinary live reads. Before any output is energised the
   procedure *reads* the engine state rather than assuming it, because the
   safety gate will not act on an assumption.
3. Actuator steps go through the same gate and the same workstation-owned
   deadline as a manual pulse. A refusal stops the run and says why; aborting
   releases every output.
4. The verdict is phrased like a plausibility check: a level, what was
   measured, and the usual suspects. It is a place to start looking, never a
   diagnosis.
