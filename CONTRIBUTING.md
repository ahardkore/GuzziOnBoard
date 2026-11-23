# Contributing to GuzziOnBoard

Thanks for looking. This project is a motorcycle diagnostics and calibration
workstation where a wrong answer costs an engine, so the contribution rules are
stricter than a typical web app's — and they are mostly about evidence, not
style.

## The one rule that matters

**Do not claim a capability the code cannot demonstrate.** A decoder that
"probably" works, a checksum algorithm copied without a source, a map table
guessed from a similar ECU — those are the bugs this project exists to avoid.
If something is untested, say so in the code, the docstring and the UI copy.

Concretely:

* A new protocol path needs a **source** (a public document, a cited tool's
  behaviour, or a capture someone can reproduce) and a **synthetic test**. It
  does not need hardware, but it must not pretend to have had it.
* A new catalog entry needs its `confidence` and `sources` fields filled in
  honestly. `inferred` is a valid value; "it's the same family, so it must be"
  is not.
* Physical ECU writing stays blocked until the evidence in
  [Physical validation](docs/PHYSICAL_VALIDATION.md) exists. Do not add a bypass.
* Nothing that can be sent to an ECU may be enabled by a default.

## Getting set up

```bash
python3 -m pip install -e '.[hardware,dev]'
python3 -m guzzionboard --selftest      # does the install actually work?
python3 -m pytest -q -n auto --dist loadfile   # ~2 minutes on four cores
ruff check .                            # the lint gate
```

Parallelism is opt-in (`pytest-xdist`), so a plain `python3 -m pytest -q` works
with nothing extra installed and runs serially. To run one file,
`python3 -m pytest -q tests/test_maps.py`.

Browser tests need Node 22:

```bash
npm ci
npm run test:browser            # the hosted-demo path, static server
npm run test:browser:desktop    # the desktop host path, real Python API
```

They share a results folder, so run them one after the other, not together.

## What CI checks

| Gate | What it catches |
| --- | --- |
| `ruff check .` | undefined names, unused imports, import order, mutable defaults |
| `pytest -q` on 3.11, 3.12, 3.13 | version-specific breakage |
| `scripts/build_demo_data.py --check` | a catalog change that never reached the hosted demo |
| `test_demo_mode.py` route parity | a new API route with no demo answer or refusal |
| `test_api_reference.py` | a new route missing from `docs/API.md` |
| Playwright, both configs | the page working in a tab *and* as an installed app |
| `--selftest` | a bundle missing a catalog file, XDF, web asset or worker |

## Changing the hosted demo

`web/demo-data.json` and `web/xdf-library.json` are **generated**. Never edit
them by hand:

```bash
python3 scripts/build_demo_data.py
```

If you add a route to `guzzionboard/server.py`, you must also either implement
it in `web/demo-api.js` / `web/demo-lab.js` or add it to the `LOCAL_ONLY`
refusal table with a reason a visitor can understand. `test_demo_mode.py` will
fail until you do, by design.

## Style

* Match the file you are editing. `web/app.js` and `web/styles.css` are dense
  and heavily commented; new code there follows the same comment style: *why*,
  not *what*.
* Comments explain intent and trade-offs. A comment that restates the next line
  is noise.
* No new dependency without a reason in the pull request. The runtime is
  stdlib-only by design; `pyserial`, `python-can` and `pywebview` are optional
  extras.
* Errors that reach a user must say what happened and what to do. Errors that
  reach a log should carry the traceback. Never put an internal path or a
  library message in an HTTP response.

## Pull requests

1. One concern per pull request.
2. Describe the evidence for a behavioural claim, and the failure mode you
   fixed.
3. If you touched a protocol, map or safety path, say which tests cover it.
4. Do not include ECU images, calibration archives or vendor binaries in a
   pull request. See [DynoAI and uploads](docs/DYNOAI_AND_UPLOADS.md).

## Security

Do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).

## Licence

Contributions are accepted under AGPL-3.0-only. By submitting a patch you
confirm you have the right to license it that way, and that any third-party
data or code it carries is attributed and licensed compatibly.
