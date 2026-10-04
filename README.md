# GuzziOnBoard

A modern, safety-first diagnostic workstation for Moto Guzzi motorcycles.

> **Current status:** early prototype. The UI runs against a deterministic ECU simulator; it does not communicate with a motorcycle yet. Do not connect it to a vehicle and assume service or flashing support exists.

## Direction

GuzziOnBoard is intended to improve on the split-tool experience of GuzziDiag, IAWDiag, GuzziCANDiag, and the IAW reader/writer tools with:

- one cross-platform desktop application;
- a maintainable vehicle/ECU capability catalog instead of scattered per-tool definitions;
- read-only defaults and explicit, reversible service actions;
- mandatory ECU/vehicle identification and backup verification before writes;
- live data dashboards, charts, session logging, and shareable reports;
- a simulator and recorded sessions so protocol work can be developed without a motorcycle;
- a transport layer that can support legacy K-line and modern CAN adapters independently of the UI.

## Run the prototype

The only current dependency is Python 3.11+.

```bash
python3 server.py
```

Open <http://127.0.0.1:8000>. Use **Simulator mode** to explore the dashboard, live values, fault handling, report export, and the guarded write workflow.

## Planned architecture

```text
Desktop shell (Tauri)
  └── UI (web frontend)
      └── local application API
          ├── session + safety policy
          ├── vehicle/ECU capability catalog
          ├── diagnostics service (identify, values, DTCs, actuators)
          ├── programming service (backup, verify, write, recovery)
          └── transports (simulator, serial K-line, CAN)
```

The first hardware milestone should be **read-only identification and live data**, tested against captured sessions and one owned motorcycle. ECU writing must remain disabled until protocol fixtures, backup/restore verification, power-loss handling, and a hardware test plan exist.

## Repository layout

- `index.html`, `app.js`, `styles.css` — prototype workstation UI.
- `server.py` — dependency-free local server and simulator API.
- `docs/ARCHITECTURE.md` — implementation boundaries and safety rules.

## Safety

This project is not affiliated with Piaggio or the GuzziDiag author. ECU programming can brick an ECU or create an unsafe motorcycle. The prototype intentionally exposes no real transport and no executable ECU write operation.
