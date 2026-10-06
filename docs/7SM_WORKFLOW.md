# IAW 7SM workflow

This workflow is based on the community reference **GuzziDiag for the 7SM ECU** (PDF: https://www.griso.org/GuzziDiag%20for%207SM.pdf). It is included as a product-design reference, not as a claim that GuzziOnBoard can currently perform these operations.

## Referenced 7SM families to model

The reference describes 7SM installations including California 1400, Audace, and V85 TT, with hardware families such as HW100 and HW310. A map must never be selected by motorcycle name alone: compatibility must be checked against the ECU hardware identifier and map metadata.

## Proposed guided flows

### 1. Identify

- connect using a supported FTDI K-line adapter and the correct motorcycle adapter;
- require ignition-on confirmation, engine stopped;
- read and display ECU family, hardware, software/map identifier, and checksum;
- save the complete identification response to the session log;
- keep the session read-only by default.

### 2. Backup

- confirm stable battery support before a long read;
- read the existing map into a user-selected file;
- calculate a cryptographic file hash and retain ECU-reported checksum separately;
- verify the file length and transfer completeness;
- require the user to acknowledge that the backup is readable before proceeding.

### 3. Validate a candidate map

The validator must reject a file when it cannot establish:

- matching 7SM hardware family;
- supported ECU/software family;
- expected file size and format;
- valid checksum;
- complete read/write compatibility metadata.

A filename such as `HW100` or `HW310` is not sufficient evidence. Metadata must come from parsing the file and, where possible, comparing it with the connected ECU.

### 4. Flash

The operation should be a separate, prominently guarded workflow:

1. battery/power preflight;
2. adapter and exclusive-port check;
3. ECU identity and map compatibility check;
4. verified backup check;
5. typed confirmation showing old/new identities and checksums;
6. ignition-on prompt;
7. progress with timeout and frame-level log;
8. post-write verification;
9. ignition-off countdown and session report.

The user reference warns that a failed write can brick the ECU and that a write may take approximately 20 minutes. GuzziOnBoard should therefore prevent sleep, warn about other programs using the COM port, and never hide a timeout or interruption.

### 5. Post-flash commissioning

The documented 7SM sequence is significant and should be encoded as a guided state machine rather than a loose list of buttons:

1. reset autolearning parameters;
2. wait the required settling interval;
3. handle self-learning;
4. wait and cycle ignition as required;
5. reconnect;
6. throttle self-learning;
7. wait and cycle ignition;
8. reconnect and run a final read-only health check.

Resetting autolearning parameters clears handle and throttle learning, so the UI must not present those operations as independent interchangeable actions. Any urgent-service state during this procedure must be explained without automatically clearing unrelated faults.

## Current implementation status

A published real session log now grounds the 7SM K-Line session and `1A 80`
identification layout, so that identification operation is exposed through the
physical serial transport with guided key-on/engine-off setup. It returns and
logs the captured field layout only; it does not claim a checksum. Live data,
DTCs, identifier discovery, memory read/write, checksum handling, adaptations,
and actuator commands remain unavailable because their family-specific frames,
scaling, security, and safety conditions were not recovered. Future bench work
is a project-maintainer validation task, not a customer protocol exercise.
