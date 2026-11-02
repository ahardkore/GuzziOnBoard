/* Frame lab: J1939 identifier arithmetic, ISO-TP segmentation and KWP2000
 * framing, all offline. The KWP helpers mirror the runtime rules in
 * guzzionboard/protocol/kwp2000.py (format byte, addressing, low-byte sum), so
 * a frame composed here is the frame the desktop build would send; nothing in
 * this file opens a port or contacts an ECU. */
'use strict';

const FRAME_LAB_PGN = {
  59904: 'Request',
  60160: 'Transport Protocol · Data Transfer',
  60416: 'Transport Protocol · Connection Management',
  60928: 'ISO Address Claim',
  61443: 'EEC2 · Engine control',
  61444: 'EEC1 · Engine speed and torque',
  65134: 'ERC1 · Retarder',
  65262: 'ET1 · Engine temperature',
  65265: 'CCVS · Vehicle speed',
  65266: 'LFE · Fuel rate',
  65276: 'DD · Dash display',
};

const J1939_BROADCAST = 0xff;

function frameHex(bytes) {
  return Array.from(bytes, (b) => b.toString(16).toUpperCase().padStart(2, '0')).join(' ');
}

function parseHexBytes(text) {
  const cleaned = String(text || '').replace(/0x/gi, '').replace(/[^0-9a-fA-F]/g, '');
  if (cleaned.length % 2) throw new Error('Hex needs an even number of digits.');
  const out = new Uint8Array(cleaned.length / 2);
  for (let i = 0; i < out.length; i += 1) out[i] = parseInt(cleaned.slice(i * 2, i * 2 + 2), 16);
  return out;
}

function decodeJ1939(identifier) {
  if (!Number.isInteger(identifier) || identifier < 0 || identifier > 0x1fffffff) {
    throw new Error('A J1939 identifier is a 29-bit number.');
  }
  const priority = (identifier >>> 26) & 0x7;
  const edp = (identifier >>> 25) & 0x1;
  const dp = (identifier >>> 24) & 0x1;
  const pf = (identifier >>> 16) & 0xff;
  const ps = (identifier >>> 8) & 0xff;
  const sa = identifier & 0xff;
  const pdu1 = pf < 240;
  const pgn = (edp << 17) | (dp << 16) | (pf << 8) | (pdu1 ? 0 : ps);
  return {
    identifier,
    hex: `0x${identifier.toString(16).toUpperCase().padStart(8, '0')}`,
    priority,
    edp,
    dp,
    pf,
    ps,
    sa,
    pdu: pdu1 ? 'PDU1 (destination specific)' : 'PDU2 (broadcast)',
    destination: pdu1 ? ps : J1939_BROADCAST,
    pgn,
    pgnHex: `0x${pgn.toString(16).toUpperCase()}`,
    pgnName: FRAME_LAB_PGN[pgn] || 'not in the bundled name table',
    reserved: edp === 1 ? 'EDP set — ISO 15765 (CAN) extended page' : '',
  };
}

function encodeJ1939({ priority = 6, pgn, sa = 0, destination } = {}) {
  if (!Number.isInteger(pgn) || pgn < 0 || pgn > 0x3ffff) throw new Error('PGN must be 0..0x3FFFF.');
  if (!Number.isInteger(sa) || sa < 0 || sa > 0xff) throw new Error('Source address must be 0..0xFF.');
  const edp = (pgn >>> 17) & 0x1;
  const dp = (pgn >>> 16) & 0x1;
  const pf = (pgn >>> 8) & 0xff;
  const ps = pgn & 0xff;
  const pdu1 = pf < 240;
  const dest = pdu1 ? (destination === undefined ? 0xff : destination) : ps;
  if (!Number.isInteger(dest) || dest < 0 || dest > 0xff) throw new Error('Destination must be 0..0xFF.');
  const identifier = ((priority & 0x7) << 26) | (edp << 25) | (dp << 24) | (pf << 16) | (dest << 8) | sa;
  return { identifier: identifier >>> 0, hex: `0x${(identifier >>> 0).toString(16).toUpperCase().padStart(8, '0')}` };
}

function parseCandumpLine(line) {
  const text = String(line || '').trim();
  if (!text || text.startsWith('#')) return null;
  // candump formats: "(1612345678.123456) can0 123#DEADBEEF" or "can0 18FEF100 [8] 01 02 ..."
  const hashForm = text.match(/(?:\(([\d.]+)\)\s+)?([\w-]+)\s+([0-9A-Fa-f]{3,8})#([0-9A-Fa-f]*)/);
  if (hashForm) {
    const identifier = parseInt(hashForm[3], 16);
    const extended = hashForm[3].length > 3;
    return {
      time: hashForm[1] ? Number(hashForm[1]) : null,
      bus: hashForm[2],
      identifier: extended ? identifier >>> 0 : identifier,
      extended,
      data: parseHexBytes(hashForm[4]),
      raw: text,
    };
  }
  const bracketForm = text.match(/(?:\(([\d.]+)\)\s+)?([\w-]+)\s+([0-9A-Fa-f]{3,8})\s+\[(\d+)\]\s*(.*)$/);
  if (bracketForm) {
    const identifier = parseInt(bracketForm[3], 16);
    return {
      time: bracketForm[1] ? Number(bracketForm[1]) : null,
      bus: bracketForm[2],
      identifier,
      extended: bracketForm[3].length > 3,
      data: parseHexBytes(bracketForm[5]),
      raw: text,
    };
  }
  return null;
}

function describeFrames(text) {
  const lines = String(text || '').split(/\r?\n/);
  const frames = [];
  const skipped = [];
  lines.forEach((line, index) => {
    if (!line.trim()) return;
    const frame = parseCandumpLine(line);
    if (!frame) {
      skipped.push({ line: index + 1, text: line.trim() });
      return;
    }
    let j1939 = null;
    try {
      if (frame.extended) j1939 = decodeJ1939(frame.identifier);
    } catch (_) {
      j1939 = null;
    }
    frames.push({ ...frame, j1939, length: frame.data.length });
  });
  const byId = new Map();
  frames.forEach((frame) => {
    const key = frame.identifier;
    if (!byId.has(key)) byId.set(key, { identifier: key, count: 0, maxLength: 0, sample: '', j1939: frame.j1939 });
    const entry = byId.get(key);
    entry.count += 1;
    entry.maxLength = Math.max(entry.maxLength, frame.length);
    if (!entry.sample) entry.sample = frameHex(frame.data);
  });
  return { frames, skipped, census: Array.from(byId.values()).sort((a, b) => b.count - a.count) };
}

/** Split a payload into ISO 15765-2 classic-CAN frames (8-byte data field). */
function isotpSegments(payload, { padByte = 0xcc, pad = true } = {}) {
  const bytes = payload instanceof Uint8Array ? payload : parseHexBytes(payload);
  if (!bytes.length) throw new Error('Nothing to segment.');
  if (bytes.length > 4095) throw new Error('Classic ISO-TP carries at most 4095 bytes.');
  const frames = [];
  const padTo = (out) => {
    if (!pad) return out;
    while (out.length < 8) out.push(padByte & 0xff);
    return out;
  };
  if (bytes.length <= 7) {
    frames.push({ kind: 'SF', pci: 0x00 | bytes.length, data: padTo([bytes.length, ...bytes]) });
    return frames;
  }
  const length = bytes.length;
  frames.push({ kind: 'FF', pci: 0x10 | ((length >> 8) & 0x0f), data: padTo([0x10 | ((length >> 8) & 0x0f), length & 0xff, ...bytes.slice(0, 6)]) });
  let offset = 6;
  let index = 1;
  while (offset < bytes.length) {
    const chunk = bytes.slice(offset, offset + 6);
    frames.push({ kind: 'CF', pci: 0x20 | (index & 0x0f), data: padTo([0x20 | (index & 0x0f), ...chunk]) });
    offset += 6;
    index = (index + 1) & 0x0f;
  }
  return frames;
}

function isotpReassemble(input) {
  const frames = (Array.isArray(input) ? input : String(input).split(/[\r\n,;]+/))
    .map((entry) => {
      if (typeof entry === 'string') {
        const frame = parseCandumpLine(entry);
        if (frame) return frame.data;
        return parseHexBytes(entry);
      }
      return entry;
    })
    .filter((data) => data && data.length);
  if (!frames.length) throw new Error('No frames to reassemble.');
  const first = frames[0];
  const type = first[0] >>> 4;
  if (type === 0) {
    const size = first[0] & 0x0f;
    if (!size || size > first.length - 1) throw new Error('Single frame length does not match its data.');
    return { kind: 'SF', length: size, payload: frameHex(first.slice(1, 1 + size)), complete: true, frames: 1 };
  }
  if (type !== 1) throw new Error('A reassembly has to start with a single or first frame.');
  const total = ((first[0] & 0x0f) << 8) | first[1];
  if (!total || total <= 7) throw new Error('First frame declares an impossible length.');
  const out = Array.from(first.slice(2, 8));
  let expect = 1;
  for (let i = 1; i < frames.length && out.length < total; i += 1) {
    const data = frames[i];
    const kind = data[0] >>> 4;
    if (kind !== 2) throw new Error(`Frame ${i + 1} is not a consecutive frame.`);
    const sequence = data[0] & 0x0f;
    if (sequence !== (expect & 0x0f)) throw new Error(`Consecutive frame ${i + 1} carries sequence ${sequence}, expected ${expect & 0x0f}.`);
    expect += 1;
    for (let j = 1; j < data.length && out.length < total; j += 1) out.push(data[j]);
  }
  return {
    kind: 'FF',
    length: total,
    payload: frameHex(out),
    complete: out.length === total,
    received: out.length,
    frames: frames.length,
    note: out.length === total ? '' : 'More consecutive frames are needed to complete the payload.',
  };
}

/** KWP2000 request framing, matching guzzionboard/protocol/kwp2000.py. */
function kwpEncode(payloadHex, { target = 0x10, source = 0xf1, addressed = true, forceLong = false } = {}) {
  const payload = payloadHex instanceof Uint8Array ? Array.from(payloadHex) : Array.from(parseHexBytes(payloadHex));
  if (!payload.length) throw new Error('A KWP2000 request needs at least a service identifier.');
  if (payload.length > 255) throw new Error('KWP2000 payloads stop at 255 bytes.');
  const out = [];
  const short = payload.length <= 63 && !forceLong;
  if (addressed) {
    out.push((short ? 0x80 : 0x80) | (short ? payload.length : 0));
    out.push(target & 0xff, source & 0xff);
  } else {
    if (short) out.push(payload.length);
    else out.push(0x00, payload.length);
  }
  if (addressed && !short) out.push(payload.length);
  out.push(...payload);
  const sum = out.reduce((a, b) => a + b, 0) & 0xff;
  return { bytes: new Uint8Array(out.concat(sum)), hex: frameHex(out.concat(sum)), checksum: sum, format: out[0], long: !short };
}

function kwpDecode(input, { addressed = true } = {}) {
  const bytes = input instanceof Uint8Array ? Array.from(input) : Array.from(parseHexBytes(input));
  if (bytes.length < 2) throw new Error('Too short to be a KWP2000 frame.');
  const body = bytes.slice(0, -1);
  const stored = bytes[bytes.length - 1];
  const computed = body.reduce((a, b) => a + b, 0) & 0xff;
  const format = body[0];
  let length;
  let payloadStart;
  let target = null;
  let source = null;
  if (format === 0x80 || format === 0x00) {
    length = body[addressed ? 3 : 1];
    payloadStart = addressed ? 4 : 2;
    if (addressed) {
      target = body[1];
      source = body[2];
    }
  } else {
    length = format & 0x3f;
    payloadStart = addressed ? 3 : 1;
    if (addressed) {
      target = body[1];
      source = body[2];
    }
  }
  const payload = body.slice(payloadStart, payloadStart + length);
  return {
    format,
    target,
    source,
    length,
    payload: frameHex(payload),
    declared: length,
    actual: payload.length,
    checksumOk: stored === computed,
    stored,
    computed,
    ok: stored === computed && payload.length === length,
  };
}

if (typeof window !== 'undefined') {
  window.gobFrameLab = {
    decodeJ1939,
    encodeJ1939,
    parseCandumpLine,
    describeFrames,
    isotpSegments,
    isotpReassemble,
    kwpEncode,
    kwpDecode,
    parseHexBytes,
    frameHex,
    PGN_NAMES: FRAME_LAB_PGN,
  };
}

/* ---- panel wiring ------------------------------------------------------- */

if (typeof document !== 'undefined') {
  const el = (id) => document.getElementById(id);
  const setText = (id, text) => {
    const node = el(id);
    if (node) node.textContent = text;
  };

  const decodeBtn = el('frameLabDecode');
  if (decodeBtn) {
    decodeBtn.onclick = () => {
      setText('frameLabOut', '');
      try {
        const result = describeFrames(el('frameLabIn').value);
        if (!result.frames.length) {
          setText('frameLabOut', result.skipped.length
            ? 'No candump lines understood. Accepted: "can0 123#DEADBEEF" and "(t) can0 18FEF100 [8] 01 02 …".'
            : 'Paste one frame per line.');
          return;
        }
        const head = `${result.frames.length} frame(s), ${result.census.length} distinct identifier(s)`
          + (result.skipped.length ? `, ${result.skipped.length} line(s) skipped` : '');
        const census = result.census.map((entry) => {
          const j = entry.j1939;
          const name = j ? ` · PGN ${j.pgn} ${j.pgnName} · SA 0x${j.sa.toString(16).toUpperCase()} · ${j.pdu}` : '';
          return `0x${entry.identifier.toString(16).toUpperCase().padStart(entry.identifier > 0x7ff ? 8 : 3, '0')}`
            + ` ×${entry.count} · ${entry.maxLength} byte${entry.maxLength === 1 ? '' : 's'} · ${entry.sample}${name}`;
        });
        const skipped = result.skipped.map((row) => `line ${row.line} skipped: ${row.text}`);
        setText('frameLabOut', [head, '', ...census, ...(skipped.length ? ['', ...skipped] : [])].join('\n'));
      } catch (error) {
        setText('frameLabOut', `Not decoded: ${error.message}`);
      }
    };
  }

  const buildBtn = el('isotpBuild');
  if (buildBtn) {
    buildBtn.onclick = () => {
      setText('isotpOut', '');
      try {
        const payload = parseHexBytes(el('isotpPayload').value);
        const padByte = parseInt(el('isotpPad').value, 16);
        if (!Number.isInteger(padByte)) throw new Error('Padding byte must be two hex digits.');
        const frames = isotpSegments(payload, { padByte, pad: el('isotpPadOn').checked });
        setText('isotpOut', `${payload.length} byte payload → ${frames.length} frame(s), padding 0x${padByte.toString(16).toUpperCase()}\n`
          + frames.map((frame) => `${frame.kind}  ${frameHex(frame.data)}`).join('\n'));
      } catch (error) {
        setText('isotpOut', `Not segmented: ${error.message}`);
      }
    };
  }

  const joinBtn = el('isotpJoin');
  if (joinBtn) {
    joinBtn.onclick = () => {
      setText('isotpInOut', '');
      try {
        const result = isotpReassemble(el('isotpIn').value);
        setText('isotpInOut', `${result.kind} · declared ${result.length} byte(s) · `
          + (result.complete ? 'complete' : `incomplete (${result.received || 0} received)`)
          + `\n${result.payload}` + (result.note ? `\n${result.note}` : ''));
      } catch (error) {
        setText('isotpInOut', `Not reassembled: ${error.message}`);
      }
    };
  }

  const kwpBuild = el('kwpBuild');
  if (kwpBuild) {
    kwpBuild.onclick = () => {
      setText('kwpOut', '');
      try {
        const target = parseInt(el('kwpTarget').value, 16);
        const source = parseInt(el('kwpSource').value, 16);
        if (!Number.isInteger(target) || !Number.isInteger(source)) throw new Error('Addresses are two hex digits.');
        const result = kwpEncode(el('kwpPayload').value, {
          target, source, addressed: el('kwpAddressed').checked, forceLong: el('kwpLong').checked,
        });
        const back = kwpDecode(result.bytes, { addressed: el('kwpAddressed').checked });
        setText('kwpOut', `${result.hex}\nformat 0x${result.format.toString(16).toUpperCase()} · `
          + `${result.long ? 'long' : 'short'} form · checksum 0x${result.checksum.toString(16).toUpperCase().padStart(2, '0')}\n`
          + `round trip: payload ${back.payload} · declared ${back.declared} · ${back.ok ? 'checksum ok' : 'checksum mismatch'}`);
      } catch (error) {
        setText('kwpOut', `Not built: ${error.message}`);
      }
    };
  }
}
