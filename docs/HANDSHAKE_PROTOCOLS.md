# Diagnostic handshake survey

Research date: **2026-10-06**. This note answers a narrow question: which
other diagnostic handshakes are relevant to the motorcycles GuzziOnBoard
catalogues, and which changes can be made without pretending that unrelated
protocols are interchangeable?

## Executive result

There is no missing universal “third K-Line handshake” for the Marelli
KWP2000 families. The useful improvement is to implement the two applicable
ISO 14230 initialisation paths correctly and to distinguish them from other
protocols that happen to use the same wire:

1. **KWP2000 fast init** — 300 ms initial idle; K-Line low at 25 ms and high
   at the 50 ms mark; immediately send StartCommunication; accept the link
   only after a checksum-valid positive `C1` response with two key bytes.
2. **KWP2000 5-baud init** — 300 ms idle; send the address at 5 baud; require
   `55 KW1 KW2`; return `~KW2` after W4; require the ECU's `~address` reply.
3. **ISO 9141-2 5-baud init** looks electrically identical but selects a
   different message protocol through keywords `08 08` or `94 94`. The
   workstation now identifies and reports that result rather than treating it
   as a valid KWP2000 link. Adding ISO 9141 PID/header support would be a
   separate feature, and none of the catalogued Marelli profiles asks for it.

The old implementation had four concrete handshake defects:

- any two received bytes counted as fast-init success, without checksum,
  service or address validation;
- `DiagnosticsService` sent StartCommunication a second time after the
  physical transport had already completed it;
- auto mode waited only 300 ms between failed fast and slow attempts;
- neither path gave the line the standard W5 idle time before first init.

All four are corrected. The Garage also exposes profile-default, automatic,
fast and 5-baud choices, and the Link view reports the selected protocol and
every automatic attempt.

## What the standards actually define

### ISO 14230 / KWP2000 on K-Line

The ISO 14230-2 data-link draft defines CARB, 5-baud and fast initialisation.
The two non-CARB KWP paths are the ones relevant here.

#### 5-baud timing

| Symbol | Required timing | Meaning |
|---|---:|---|
| W5 | at least 300 ms | idle before the address |
| bit time | 200 ms | 5 baud address, start + eight LSB-first bits + stop |
| W1 | 60–300 ms | address end to `55` sync |
| W2 | 5–20 ms | sync to KW1 |
| W3 | 0–20 ms | KW1 to KW2 |
| W4 | 25–50 ms | KW2 to tester's `~KW2`, and `~KW2` to ECU's `~address` |

A successful 5-baud handshake establishes communication by itself;
StartCommunication must **not** follow it.

#### Fast timing and frame

| Symbol | Required timing | Meaning |
|---|---:|---|
| W5 / Tidle | 300 ms on first attempt | bus idle |
| TiniL | 24–26 ms | K-Line low |
| TWuP | 49–51 ms from first falling edge | first StartCommunication bit |

The first message must carry target and source addresses and no extra length
byte. Functional OBD addressing produces the familiar request:

```text
C1 33 F1 81 66
```

A valid positive response has service `C1` and two key bytes. Receiving noise,
an echo, a truncated frame, a bad checksum or an unrelated positive response
is not successful initialisation.

Primary references:

- ISO/DIS 14230-2, *Keyword Protocol 2000 — Data link layer*, sections
  5.1.5.2, 5.1.5.3 and 6.1:
  <https://www.internetsomething.com/kwp/KWP2000%20ISO%2014230-2%20KLine%20.pdf>
- KWP2000 Recommended Practice v1.5 (1997), timing/key-byte guidance:
  <https://www.internetsomething.com/kwp/kwp2000_recommended_guidlines.pdf>
- Volkswagen Group of America, *K-line Communication Description* (2009), a
  particularly clear comparison of all three legislated K-Line protocols and
  their retry failure mode:
  <https://www.obdclearinghouse.com/Files/viewFile?fileID=1380>

### The auto-fallback trap

A slow-only ECU can see the 25 ms low pulse of a failed fast attempt as the
beginning of a 5-baud address. Some implementations do not reject that address
until its complete two-second window has elapsed. Starting the real 5-baud
address after W5 alone means the ECU begins listening halfway through it and
can fail on every retry.

The VW paper gives two safe strategies: try 5-baud before fast, or wait the
full address window + W1 + W5 (**2.6 seconds**) after a failed fast attempt.
GuzziOnBoard keeps fast-first because it is the documented default for the
newer IAW families, but now uses the safe 2.6-second fallback.

### ISO 9141-2

ISO 9141-2 shares the K-Line and five-baud electrical sequence. Its keyword
pairs (`08 08` or `94 94`) select ISO 9141 framing (for legislated OBD, the
`68 6A F1 ...` header), not ISO 14230 framing. A valid electrical handshake is
therefore not enough to claim the current application stack can talk to it.
The new classifier returns `iso9141-2` and a clear unsupported-message-layer
error.

This is a future extension only if a supported motorcycle is demonstrated to
need ISO 9141 services. It should then be a separate protocol module, not a
special case in `kwp2000.py`.

## Other protocols investigated

| Protocol / handshake | How it starts | Relevance here | Decision |
|---|---|---|---|
| **KWP1281 / KW1281** | 5-baud module address, `55` sync and keywords, then a byte-complemented, counter-based block exchange | Mostly older Volkswagen-group modules. It shares the wake-up shape but not KWP2000 framing or services. | Do not add to Marelli profiles. A future implementation needs a separate block protocol. See <https://github.com/mnaberez/vwradio/blob/main/kwp1281_tool/README.md>. |
| **OEM motorcycle K-Line variants** | Manufacturer-specific pulse and magic-byte sequences; one documented Honda variant uses 70 ms low, 120 ms high, then proprietary requests | Useful evidence that “K-Line” does not imply “KWP2000,” but no catalogued Guzzi/Ducati/Aprilia Marelli family uses this Honda exchange. | Do not guess or probe proprietary handshakes on an IAW ECU. Reference implementation: <https://github.com/andreibaw/Honda_K-Line_KWP2000>. |
| **KWP2000 over ISO-TP/CAN** | No K-Line wake pulse. Open the CAN interface and address an ISO-TP endpoint; ISO-TP handles Single/First/Consecutive/Flow-Control frames. | Relevant to MIU G4 and possibly part of the 11MP path. The unresolved facts are CAN IDs and whether the first captured payload is framed KWP, bare KWP or UDS—not a wake pulse. | Keep passive ID discovery and virtual CAN rehearsal. Do not invent a K-Line init on CAN. Linux ISO-TP reference: <https://docs.kernel.org/networking/iso15765-2.html>. |
| **UDS over CAN** | ISO-TP endpoint first; then application services such as DiagnosticSessionControl `10 xx`, SecurityAccess `27`, and TesterPresent `3E 00` | Plausible for 11MP Euro 5/5+, but no 11MP capture settles IDs, addressing mode, DIDs or required session. | Model only after a capture. UDS session selection is an application exchange, not link initialisation. See <https://udsoncan.readthedocs.io/en/v1.18.1/udsoncan/intro.html>. |
| **DoIP / ISO 13400** | UDP vehicle discovery, TCP connection and routing activation, then diagnostic payloads | No catalogued motorcycle or connector evidence indicates Automotive Ethernet/DoIP. | Out of scope until hardware evidence exists. ISO overview: <https://www.iso.org/standard/68424.html>. |

## Marelli-specific evidence and limits

- The IAW 5AM capture-backed neighbour project uses exactly the two KWP paths:
  fast 25/25 ms + StartCommunication, or address `0x33` +
  `55/KW1/KW2/~KW2/~address`:
  <https://github.com/Vasiy/onboard-logger>.
- Public 7SM logs repeatedly show `Init Ok`, identification, `Diagnostic
  started`, then `Baudrate switched`. This proves a post-init session/baud
  transition, not a third wake-up protocol. Example:
  <https://www.apriliaforum.com/forums/archive/index.php/t-340608.html>.
- The exact 7SM baud-switch request is not in the public log. It remains
  unimplemented rather than inferred.
- No public source found a different init for 15M/15RC/16M/P8 that is stronger
  than the current catalog assignments. Those assignments therefore retain
  their existing confidence; improved negotiation does not promote protocol
  evidence.

## Implementation map

| Finding | Code / UI change |
|---|---|
| W5 idle before either K-Line init | `transports/kline.py` |
| Strict 25/25 scheduling | `KLineTransport._fast_init` |
| Validate checksum, `C1`, two keys and tester target | `KLineTransport._fast_init` |
| Validate `55`, both keywords, `~KW2` echo and `~address` | `KLineTransport._slow_init` |
| Distinguish ISO 9141 keyword pairs | `keyword_protocol` |
| Safe 2.6 s fast→slow retry | `KLineTransport.initialize(method="auto")` |
| Never send StartCommunication twice | `InitResult.handshake_complete` + `DiagnosticsService.connect` |
| Preserve pre-session fast-init raw frames | `InitResult.request/response` + session logger |
| Operator override without changing catalog evidence | Garage → K-Line handshake selector |
| Make negotiation diagnosable | Link view protocol, key bytes and attempt transcript |

## What still needs hardware

These changes make the client standards-correct; they do not turn inference
into a bench result. The first real-bike sessions should record:

1. scope or logic-analyser timing around wake-up;
2. the complete raw StartCommunication request/response or slow keywords;
3. ECU family and hardware/software identity;
4. whether the catalog default worked before an override;
5. for 7SM, the exact diagnostic-session and baud-switch frames;
6. for MIU G4/11MP, passive CAN IDs, addressing mode, padding and the first
   unwrapped diagnostic payload.

Until those captures exist, hardware remains labelled unvalidated and the
existing confidence/safety gates continue to apply.
