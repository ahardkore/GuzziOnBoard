#!/usr/bin/env python3
"""Generate ``web/demo-data.json`` — the catalog snapshot the hosted demo runs on.

GitHub Pages has no Python process, so the workstation UI served from a static
host cannot call the real ``/api`` endpoints. ``web/demo-api.js`` answers them
in the browser instead, and it answers them *from this file*: the same catalog
the Python workstation loads, exported verbatim rather than retyped.

Nothing here is invented. Every payload below is produced by the catalog's own
``as_dict()`` methods, so the demo cannot drift into claiming coverage the
real tool does not have. ``tests/test_demo_mode.py`` regenerates the file and
fails if the checked-in copy differs.

Usage::

    python3 scripts/build_demo_data.py          # write web/demo-data.json
    python3 scripts/build_demo_data.py --check  # exit 1 if it is out of date
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guzzionboard import __version__                       # noqa: E402
from guzzionboard import procedures as procedures_mod      # noqa: E402
from guzzionboard import rpmsignal                         # noqa: E402
from guzzionboard import tools as tools_mod                # noqa: E402
from guzzionboard.catalog import CATALOG_DIR, ECU_DIR, load_catalog  # noqa: E402
from guzzionboard.derived import CHANNELS as DERIVED_CHANNELS        # noqa: E402
from guzzionboard.maps import BUNDLED_XDF_DIR, load_bundled_xdfs     # noqa: E402
from guzzionboard.transports.simulator import FAULTS as SIM_FAULTS   # noqa: E402
from guzzionboard.transports.simulator import SimulatedEcu           # noqa: E402
from guzzionboard.workstation import Workstation                     # noqa: E402

OUTPUT = ROOT / "web" / "demo-data.json"

#: Internal parameter fields the browser simulator needs in order to encode a
#: raw value and decode it back the way the Python stack does.
PARAM_INTERNALS = (
    "offset", "length", "endian", "signed", "scale", "bias", "recip",
    "digits", "dead",
)


def _raw_ecu(ecu_id: str) -> dict:
    return json.loads((ECU_DIR / f"{ecu_id}.json").read_text(encoding="utf-8"))


def _xdf_index() -> list[dict]:
    """The bundled TunerPro definitions, with the URL the browser can fetch.

    The XDF files themselves are already published by GitHub Pages (they are
    ordinary files in the repository), so the demo does not copy them: it
    only needs to know what exists and where. ``url`` is relative to
    ``web/index.html``.
    """
    out: list[dict] = []
    for xdf in load_bundled_xdfs():
        entry = xdf.describe()
        relative = Path(entry["path"]).relative_to(BUNDLED_XDF_DIR.parent.parent)
        entry["path"] = str(relative)
        entry["url"] = "../" + str(relative).replace("\\", "/")
        out.append(entry)
    return out


def _procedures() -> list[dict]:
    """Guided-test definitions, minus the Python-side verdict callables.

    The verdict functions are reimplemented in ``web/demo-lab.js``; the
    step list, wording and caveats come from here so the two cannot drift.
    """
    out = []
    for procedure in procedures_mod.PROCEDURES:
        entry = procedure.as_dict(None)
        entry.pop("available", None)
        entry.pop("missing", None)
        out.append(entry)
    return out


def build() -> dict:
    catalog = load_catalog()
    shared_dtc = json.loads(
        (CATALOG_DIR / "dtc_sae.json").read_text(encoding="utf-8")
    )["codes"]

    profiles: dict[str, dict] = {}
    for ecu_id, profile in catalog.ecus.items():
        raw = _raw_ecu(ecu_id)

        params: dict[str, dict] = {}
        for p in profile.parameters:
            entry = {field: getattr(p, field) for field in PARAM_INTERNALS}
            entry["local_id"] = p.local_id
            entry["states"] = p.states
            params[p.key] = entry

        actuators = {
            a.key: {"on_command": a.on_command, "off_command": a.off_command}
            for a in profile.actuators
        }
        routines = {
            r.key: {"params": list(r.params), "expect": r.expect}
            for r in profile.routines
        }

        # Only what this family adds on top of the shared SAE table.
        overrides = {
            code: text
            for code, text in (raw.get("dtc_descriptions") or {}).items()
            if shared_dtc.get(code) != text
        }

        # The identity block the simulated ECU answers with, taken from the
        # simulator itself rather than copied by hand.
        identity = SimulatedEcu(profile)._default_identity()

        profiles[ecu_id] = {
            "parameters": params,
            "actuators": actuators,
            "routines": routines,
            "identity": identity,
            "dtc_overrides": overrides,
            "session": profile.session,
            "identification": raw.get("identification", {}),
        }

    api_catalog = {
        "summary": catalog.summary(),
        "makes": catalog.makes(),
        "models": [
            {"model": model, "variants": [v.as_dict() for v in catalog.find(model)]}
            for model in catalog.models()
        ],
        "vehicles": [
            {
                "make": v.make, "model": v.model,
                "year_from": v.year_from, "year_to": v.year_to, "ecu": v.ecu,
            }
            for v in catalog.vehicles
        ],
        "ecus": [e.as_dict() for e in catalog.ecus.values()],
    }

    return {
        "_generated_by": "scripts/build_demo_data.py",
        "_note": (
            "Catalog snapshot for the hosted browser demo. Generated from the "
            "same definitions the Python workstation loads; do not hand-edit."
        ),
        "version": __version__,
        "checklist": list(Workstation.HARDWARE_CHECKLIST),
        "catalog": api_catalog,
        "vehicle_entries": [v.as_dict() for v in catalog.vehicles],
        "profiles": profiles,
        "dtc_descriptions": shared_dtc,
        "sim_faults": [f.as_dict() for f in SIM_FAULTS],
        "derived_channels": [
            {
                "key": c.key, "name": c.name, "unit": c.unit,
                "group": c.group, "sources": list(c.sources),
                "note": c.note, "delta": c.delta, "digits": c.digits,
            }
            for c in DERIVED_CHANNELS
        ],
        # -- phase 2: what the simulated workbench needs ------------------
        "procedures": _procedures(),
        "gearing_presets": tools_mod.GEARING_PRESETS,
        "gearing_defaults": {
            "final_drive": tools_mod.Gearing().final_drive,
            "tyre": tools_mod.Gearing().tyre,
            "gears": list(tools_mod.Gearing().gears),
        },
        "rpm_wheels": {
            name: {"teeth": w.teeth, "missing": w.missing, "wheel": w.wheel}
            for name, w in sorted(rpmsignal.PRESETS.items())
        },
        "xdfs": _xdf_index(),
    }


def render(data: dict) -> str:
    return json.dumps(data, indent=1, sort_keys=False, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="do not write; fail if web/demo-data.json is out of date",
    )
    args = parser.parse_args()

    text = render(build())
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != text:
            print(
                "web/demo-data.json is out of date — "
                "run python3 scripts/build_demo_data.py",
                file=sys.stderr,
            )
            return 1
        print("web/demo-data.json is up to date")
        return 0

    OUTPUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(text) / 1024:.0f} kB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
