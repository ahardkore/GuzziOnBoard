#!/usr/bin/env python3
"""Full-capability smoke test over the live HTTP API.

Drives a GuzziOnBoard server exactly the way the UI does — in simulator
mode, against the simulated ECU that speaks the real wire protocol — and
asserts every capability area the reference-tool ecosystem provides:
diagnostics (identify / live / DTC / actuators), the XDF library, security
posture and its explicit opt-in, two-read verified backup, XDF render of
the backup bytes, and — because this session is itself the simulator —
the complete gated flash round trip (write + verified read-back), with the
write surface refusing again once programming is disabled.

Usage
-----
    python3 run_server.py --port 8099 &            # any host/port
    python3 scripts/e2e_smoke.py --port 8099

Exits non-zero if any check fails. Nothing is written outside
``~/.guzzionboard/`` (session recordings and the backup image).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8099"
RESULTS: list[tuple[str, bool, str]] = []


def api(method: str, path: str, body: dict | None = None, timeout: int = 90):
    data = json.dumps(body or {}).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except OSError as e:
        raise SystemExit(
            f"cannot reach {BASE} ({e}); start the server first: "
            "python3 run_server.py --port 8099"
        )


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name:58} {detail}")


def wait_job(timeout_s: int = 600) -> dict:
    for _ in range(timeout_s):
        time.sleep(1)
        _, progress = api("GET", "/api/memory/progress")
        if progress.get("state") in ("done", "failed"):
            return progress
    return {"state": "timeout"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--model", default="Griso 1200 8V")
    parser.add_argument("--year", type=int, default=2012)
    args = parser.parse_args()

    global BASE
    BASE = f"http://{args.host}:{args.port}"

    # -- database / selection / connection ------------------------------
    st, cat = api("GET", "/api/catalog")
    check("catalog served (vehicle database)", st == 200,
          f"keys={list(cat)[:6]}")
    st, sel = api("POST", "/api/select", {
        "make": "Moto Guzzi", "model": args.model, "year": args.year,
        "transport": "simulator"})
    check(f"select {args.model} {args.year} -> resolves ECU family",
          st == 200, json.dumps(sel)[:100])
    st, con = api("POST", "/api/connect", {"mode": "programming"})
    check("connect in programming mode (sim transport)", st == 200,
          con.get("mode", json.dumps(con)[:60]))

    # -- the diagnostic apps' job ---------------------------------------
    st, ident = api("GET", "/api/identify")
    check("identify ECU", st == 200 and bool(ident.get("fields")),
          json.dumps(ident.get("fields", {}))[:110])
    st, live = api("GET", "/api/live")
    n = len(live.get("samples", []))
    check("live data channels decoded", st == 200 and n > 10,
          f"{n} channels, e.g. "
          f"{[s.get('key') for s in live.get('samples', [])[:8]]}")
    st, sim = api("GET", "/api/sim")
    fault = (sim.get("faults") or [{}])[0].get("key")
    if fault:
        api("POST", "/api/sim/faults", {"key": fault, "active": True})
    st, dtcs = api("GET", "/api/dtcs")
    dlist = dtcs.get("dtcs") or []
    check("DTC read + decode", st == 200 and bool(dlist),
          json.dumps(dlist[0] if dlist else dtcs)[:110])
    st, refusal = api("POST", "/api/dtcs/clear", {})
    check("DTC clear gated without token (code 'token')", st == 403
          and refusal.get("code") == "token",
          f"{refusal.get('code')}: {refusal.get('error', '')[:70]}")
    st, acts = api("GET", "/api/actuators")
    check("actuator tests catalogued",
          st == 200 and len(acts.get("actuators", [])) >= 10,
          f"{len(acts.get('actuators', []))} actuators")

    # -- TunerPro's job: the XDF library, all of it ---------------------
    st, maps = api("GET", "/api/maps")
    xs = maps.get("xdfs", [])
    check("all 94 bundled XDFs visible to the app", st == 200 and len(xs) == 94,
          f"{len(xs)} XDFs")
    groups = maps.get("groups", [])
    fitting = [x for x in xs if x.get("family") == "5AM"]
    check("definitions grouped by motorcycle, with the bench ECU named",
          len(groups) > 3 and all(g.get("families") for g in groups)
          and maps.get("vehicle", {}).get("ecu_family") == "IAW 5AM"
          and len(fitting) > 10,
          f"{len(groups)} brands, {len(fitting)} definitions for the 5AM")

    # -- the explicit key-risk switch -----------------------------------
    st, sec = api("GET", "/api/security")
    check("security panel reports unverified provider + posture", st == 200,
          f"accepted={sec.get('unverified_keys_accepted')}")
    st, acc = api("POST", "/api/security/unverified", {"accept": True})
    check("operator accepts unverified key risk (audited gate method)",
          st == 200 and acc.get("allow_unverified_keys") is True,
          json.dumps(acc)[:90])

    # -- the IAW5xReaders' job: two-read verified backup ----------------
    api("POST", "/api/memory/backup", {"region": "flash"})
    bj = wait_job()
    res = bj.get("result") or {}
    path = res.get("path")
    check("backup completed, two reads verified",
          bj.get("state") == "done" and res.get("verified"),
          f"state={bj.get('state')} path={str(path)[:80]} "
          f"err={str(bj.get('error'))[:80]}")

    # -- the guaranteed way back: the base map ---------------------------
    st, bm = api("GET", "/api/memory/basemap")
    base = bm.get("base_map", {})
    check("verified backup filed as the base map (intact, re-hashed)",
          st == 200 and base.get("intact") is True
          and bm.get("restore", {}).get("ready") is True,
          f"{base.get('path', '')[:80]} {base.get('reason', '')[:60]}")

    # -- TunerPro's job on real bytes ------------------------------------
    if path:
        st, rnd = api("POST", "/api/maps/render",
                      {"path": path, "xdf": "5AM_GuzziDiag_One_Lambda_V1.41.xdf"})
        tables = rnd.get("tables", [])
        check("backup rendered as named fuel/spark tables",
              st == 200 and len(tables) > 20,
              f"{len(tables)} tables, e.g. "
              f"{[t.get('title') for t in tables[:5]]}")

    # -- the IAW5xWriters' job: gated write ------------------------------
    st, dec = api("POST", "/api/memory/check-write", {"region": "flash"})
    check("write still refused before programming opt-in",
          st == 200 and not dec.get("allowed") and not dec.get("token"),
          json.dumps(dec)[:110])
    st, en = api("POST", "/api/programming/enable", {
        "acknowledgement": "I have a verified backup and accept the risk",
        "allow_unverified_keys": True})
    check("programming opt-in (exact ack + key risk)",
          st == 200 and en.get("programming_enabled"), json.dumps(en)[:90])
    # engine observed stopped (arc-write precondition), checklist accepted
    api("POST", "/api/sim/engine", {"running": False})
    api("GET", "/api/live")
    api("POST", "/api/checklist", {"accepted": True})
    st, dec2 = api("POST", "/api/memory/check-write", {"region": "flash"})
    token = dec2.get("token")
    fails2 = [c["name"] for c in dec2.get("checks", []) if not c.get("passed")]
    # Every session here is against the simulator, and the simulated ECU
    # fully implements the write cycle — so on the sim the capability set it
    # presents has been *proven*, the gate goes green and mints a token.
    # The catalogue profile is never touched by that; a hardware session on
    # the same 5AM would still find the 'capability' check red (the overlay
    # is session-scoped — see tests/test_simulated_flash.py).
    check("write gate goes green on the simulator and mints a token",
          dec2.get("allowed") and bool(token) and fails2 == [],
          f"failed checks: {fails2}")

    # -- the IAW5xWriters' full job, on the simulated ECU ----------------
    st, wj = api("POST", "/api/memory/write",
                 {"path": path or "", "token": token or "", "region": "flash"})
    check("write accepted against the simulator", st == 202,
          json.dumps(wj if st != 202 else {})[:110])
    if st == 202:
        done = wait_job()
        wres = done.get("result") or {}
        check("sim flash round trip: write verified by read-back",
              done.get("state") == "done" and wres.get("ok") is True
              and wres.get("verified") is True,
              f"{wres.get('bytes')} bytes, sha256 {str(wres.get('sha256'))[:16]}")

    # -- the hardware-family safety gate ---------------------------------
    # "Don't flash HW1xx versions in a HW3xx ECU and vice versa. You will
    # brick your ECU!" Forge the file that bricks ECUs - byte-identical to
    # the verified backup, but its sidecar claims an HW1xx unit - and every
    # write surface has to refuse it. The forged file lives and dies inside
    # ~/.guzzionboard/, like the backup it is copied from.
    if path:
        import shutil
        forged = Path(path).with_name("hw1xx-forged-provenance-demo.bin")
        shutil.copyfile(path, forged)
        sidecar = Path(str(path) + ".json")
        meta = json.loads(sidecar.read_text(encoding="utf-8")) \
            if sidecar.exists() else {}
        identity = dict(meta.get("identity") or {})
        identity["Hardware"] = "IAW5AMHW100"
        Path(str(forged) + ".json").write_text(
            json.dumps({**meta, "ecu_id": meta.get("ecu_id", "5am"),
                        "identity": identity}),
            encoding="utf-8")

        st, hd = api("POST", "/api/memory/check-write",
                     {"region": "flash", "path": str(forged)})
        fails_h = [c["name"] for c in hd.get("checks", []) if not c.get("passed")]
        check("write gate refuses an HW1xx image by name (hardware-family)",
              st == 200 and not hd.get("allowed")
              and fails_h == ["hardware-family"],
              f"failed checks: {fails_h}")

        st, tg = api("POST", "/api/memory/check-write", {"region": "flash"})
        st, wj2 = api("POST", "/api/memory/write",
                      {"path": str(forged), "token": tg.get("token") or "",
                       "region": "flash"})
        refused = wait_job(30) if st == 202 else wj2
        check("a token cannot smuggle an HW1xx image into the ECU",
              "hardware-family" in str(refused.get("error", "")),
              str(refused.get("error", wj2))[:110])

        st, gd = api("POST", "/api/memory/check-write",
                     {"region": "flash", "path": path})
        check("the gate still green-lights the matching-family backup",
              st == 200 and gd.get("allowed") and gd.get("token"),
              json.dumps(gd.get("reason", ""))[:80])

        forged.unlink(missing_ok=True)
        Path(str(forged) + ".json").unlink(missing_ok=True)

    api("POST", "/api/programming/disable", {})
    st, dec3 = api("POST", "/api/memory/check-write", {"region": "flash"})
    check("disabling programming makes the write surface refuse again",
          st == 200 and not dec3.get("allowed") and not dec3.get("token"),
          f"reason: {str(dec3.get('reason'))[:80]}")

    # -- the support utilities, included ----------------------------------
    st, z = api("POST", "/api/tools/z2dif",
                {"text": "AFR,RPM,TPS\n11.2,2400,12\n11.4,2450,13\n"})
    check("ZT-2 CSV -> LogWorks DIF (timeline factor corrected)",
          st == 200 and z.get("dif", "").startswith("Time (s)\t"),
          f"rows={z.get('rows')}, channels={z.get('channels')}")
    st, sig = api("POST", "/api/tools/rpmsignal",
                  {"pattern": "motoguzzi", "rpm": 3000, "seconds": 0.3})
    check("bench RPM trigger signal rendered (46+2 cam preset)",
          st == 200 and sig.get("path", "").endswith(".wav"),
          f"{sig.get('teeth')}+{sig.get('missing')} {sig.get('wheel')} -> "
          f"{Path(sig.get('path', '')).name if sig.get('path') else ''}")
    st, adp = api("GET", "/api/adapter")
    driver = (adp.get("report") or {}).get("driver") or {}
    check("adapter pre-flight surfaces the vendored FTDI driver bundle",
          st == 200 and driver.get("bundle_available"),
          driver.get("bundle_path", "")[:70])
    ecus = cat.get("ecus")
    ids = ecus if isinstance(ecus, dict) else {e.get("id") for e in ecus}
    check("Mana CVT TCU cataloged (identification + discovery only)",
          "mana_tcu" in ids, "engine side resolves via Mana 850 -> 5am")

    # -- protocol evidence: confirmations and signed updates --------------
    # A fresh install pins no key, so the whole update path is closed until a
    # human chooses one. That is the shipped posture, over the wire.
    st, pu = api("GET", "/api/protocol-updates")
    check("protocol updates: shipped catalog, no key pinned, nothing applied",
          st == 200 and pu.get("status", {}).get("applied") is False
          and pu.get("status", {}).get("trusted_keys") == {}
          and pu.get("confirmations") == [],
          {"note": pu.get("note", "")[:60]} if st == 200 else str(pu)[:60])
    st, refused = api("POST", "/api/protocol-updates/check", {"url": "https://127.0.0.1:9/x.json"})
    check("protocol updates: a pack that cannot be fetched is a readable 400",
          st == 400 and "could not fetch" in str(refused.get("error", "")),
          str(refused.get("error", ""))[:80])
    st, need = api("POST", "/api/protocol-updates/apply", {"expected_sha256": "0" * 64})
    check("protocol updates: applying without the previewed pack is refused",
          st == 400 and "apply what you previewed" in str(need.get("error", "")),
          str(need.get("error", ""))[:80])
    st, built = api("POST", "/api/confirmations/build", {})
    check("a simulator session cannot become a confirmation",
          st == 400 and "simulator" in str(built.get("error", "")).lower(),
          str(built.get("error", ""))[:80])

    # -- wrap-up ---------------------------------------------------------
    st, rep = api("GET", "/api/report")
    check("session report export", st == 200,
          str(rep.get("report", {}).get("generated_at_text", ""))[:60])
    st, _ = api("POST", "/api/disconnect")
    check("disconnect clean", st == 200)

    print("\n==== SUMMARY ====")
    failed = [r for r in RESULTS if not r[1]]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} capability checks passed")
    for name, _, detail in failed:
        print(f"FAILED: {name} {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
