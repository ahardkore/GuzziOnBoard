# Bench calculators — fuel, air and lambda

Batch 4 of the [tool expansion](TOOL_EXPANSION_RESEARCH.md). Three general tools
that need no motorcycle, no file and no adapter: injector sizing, dyno
correction, and fuel blend / lambda. One file, `web/bench-calculators.js`, three
panels, and a rule that matters more than any of the arithmetic:

> **A calculated number is a starting point for a measurement, not a verified
> calibration.** Every panel says so, and the numbers that drive the result are
> shown beside it so the assumption can be argued with.

## Where the panels are

Tools → Brand dropdown → **General**. Each has a Help article: search *injector*,
*dyno correction* or *lambda*.

| Panel | What it answers |
| --- | --- |
| `#injectorPanel` | How much fuel does this power target need, and what injectors deliver it? |
| `#dynoCorrectionPanel` | What would this run have made on a standard's reference air? |
| `#fuelBlendPanel` | What does this ethanol blend do to lambda, AFR and fuel volume? |

Nothing in any of them reads a map, a log or an ECU, transmits anything, or
writes a file. They are arithmetic on what you type.

## 1. Injector & fuel-flow calculator

**Inputs:** target crank power, BSFC, injector count, maximum duty, fuel, fuel
pressure, the pressure the injector was rated at, your injector's rated flow
(optional), and engine speed.

**The chain**, in the order the panel prints it:

```
fuel mass  = power × BSFC                      lb/h
fuel volume = (lb/h × 0.45359237) / density    L/h → cc/min
per injector = volume / duty / cylinders       cc/min at your pressure
at its rating = per injector / √(P_actual/P_rated)
injection window = 120000 / rpm                ms (four-stroke, one pulse per cycle)
pulse width = window × duty                    ms
```

Worked example, straight from the panel's defaults — 100 hp, BSFC 0.50
lb/(hp·h), petrol at 0.745 kg/L, four injectors, 80 % duty, 3 bar:

| Step | Result |
| --- | --- |
| Fuel mass | 50.0 lb/h = 22.7 kg/h |
| Fuel volume | 30.4 L/h = 507 cc/min |
| Per injector | 158.6 → **159 cc/min at 3 bar** |
| At 9000 rpm | 13.33 ms window, 10.67 ms at 80 % duty |

Reverse direction: type the flow you already have and the panel prints the duty
cycle — and says so when the injectors cannot deliver the target, or when they
would sit past the ~85 % point where published flow figures stop describing
them.

**Pressure.** Flow scales with the square root of the pressure difference across
the injector. Running a 3 bar injector at 4 bar multiplies its flow by
√(4/3) = 1.155, so a 240 cc/min injector becomes 277 cc/min. The panel converts
in both directions and shows the ratio.

**Fuels.** Stoichiometric ratio, density and a default BSFC per fuel; choosing a
fuel moves the BSFC default *only while the field still holds the previous
default*, so a number you typed is never overwritten.

## 2. Dyno correction & air density

**Inputs:** measured power (hp, kW or Nm — returned in the same unit), standard,
air temperature, barometric pressure *or* altitude, relative humidity, and a
"boosted engine" flag.

Air first: saturation vapour pressure from the Buck equation, dry air pressure =
total − vapour, then density from the ideal-gas partial pressures (287.058 and
461.495 J/(kg·K)). If you give an altitude instead of a pressure, ISA supplies
one: `1013.25 × (1 − 2.25577e-5 h)^5.25588`.

Then the standard:

| Standard | Reference | Form used |
| --- | --- | --- |
| SAE J1349 | 990 hPa dry, 298.15 K | `CF = 1.176 × (990/P_dry) × (T/298.15)^0.5 − 0.176` |
| DIN 70020 | 1013.25 hPa, 293.15 K | `CF = (P_ref/P) × (T/T_ref)` |
| SAE J607 (STD) | 1013.25 hPa, 288.15 K | density form, the same shape |
| ISO 1585 / EEC 80/1269 | 1000 hPa, 293.15 K | density form, approximate |
| Uncorrected | — | factor 1, density ratio shown for context |

At 25 °C and 1013 hPa a 100 hp run reads: J1349 0.973 → 97.3 hp, DIN 70020
1.017 → 101.7 hp, SAE J607 1.035 → 103.5 hp. That is the honest headline: the
standard moves the number by more than most bolt-on parts do, so quote it with
the figure.

Two limits are stated in the panel rather than buried:

- At reference conditions J1349 gives exactly 1.000 — a useful check that the
  arithmetic is the published form and not an approximation of it.
- **J1349 is defined for naturally aspirated engines.** A boosted run is
  computed (people ask) and flagged as not a J1349 result.

The humidity term is applied where the standard defines one (J1349, through dry
pressure); DIN, J607 and ISO are presented in density form and labelled
*approximate* rather than pretending otherwise.

## 3. Fuel blend, λ & stoichiometry

**Inputs:** ethanol percentage, whether your number is lambda or AFR, and
optionally the petrol duty cycle you run today.

**The blend model** is linear on volume fraction between petrol (14.7:1,
0.745 kg/L, 43.5 MJ/kg) and ethanol (9.0:1, 0.789 kg/L, 26.8 MJ/kg):

```
stoich  = 14.7 × (1 − f) + 9.0 × f
density = 0.745 × (1 − f) + 0.789 × f
LHV     = mass-weighted between petrol and ethanol
```

At E85 that gives 9.855:1, 0.7824 kg/L and 22.8 MJ/L. Handbooks quote E85 at
9.8:1; the difference is 0.6 % and it is **stated rather than hidden**, because
both the injector panel and this one use the same model, so at least they agree
with each other.

**What the panel shows:** lambda → AFR on the blend *and* on petrol, the volume
ratio for the same lambda — 1.420 × for E85 — and the comparison row for E0, E10,
E85 and E100. Give it a measured petrol duty cycle and it converts: 60 % on
petrol becomes 85.2 % on E85, past the linear knee, and the panel says which of
the two warnings applies.

**Petrol-family fuels are derived from this model**, not typed in twice:
`BENCH_FUELS.petrol`, `.e10` and `.e85` are built from `ethanolBlend(...)`.
Methanol (6.5:1) and diesel (14.5:1) are separate substances and carry their own
published constants.

## Why lambda and not AFR

Lambda is the ratio of actual AFR to the fuel's stoichiometric AFR, so it is the
one number that means the same thing on petrol, E10, E85 and methanol. Two logs
in AFR are only comparable when the assumed stoichiometric ratio is identical —
which is exactly the assumption a fuel change breaks. If the wideband controller
can output lambda, log that; the
[wideband lab](OFFLINE_TOOLKIT.md) already converts either way.

## Tests

- `tests/browser/bench-calculators.spec.mjs` — 12 cases. Every expected value is
  hand-computed in a comment beside the assertion: the 507 cc/min chain, the
  square-root pressure correction, the 126.8 % under-sized case, J1349 = 1.000 at
  reference air, the 0.973 / 1.017 / 1.035 / 1.017 standard table, the 845.6 hPa
  altitude estimate, E85 at 9.855:1 and 1.420 ×, the two duty warnings, thirteen
  rejection messages, the BSFC-follows-fuel rule and live recalculation.
- `tests/test_bench_calculators.py` — 8 guards a browser test cannot express:
  the constants are the ones this document cites, petrol-family fuels are
  derived from the blend model, the E85 difference is documented, the wideband
  lab and the calculators agree on methanol and diesel, every panel carries a
  caution, and the file contains no network, storage or desktop-host call.

## Limits, stated plainly

- BSFC, ethanol percentage, injector flow ratings and dyno corrections are all
  inputs supplied by a person or a vendor. The tools are arithmetic; they cannot
  verify any of them.
- None of the three tools recommends a mixture or a component. They show what
  follows from the numbers you gave them.
- Nothing here is a write path, a programming step or a substitute for a
  wideband reading.
