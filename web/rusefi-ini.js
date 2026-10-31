/* Restricted INI signature extraction and rusEFI's documented lookup URL.
 * See https://wiki.rusefi.com/INI-lookup-logic/. This is not a full INI parser.
 */
'use strict';
const RusefiIni = (() => {
  const MAX_BYTES = 2 * 1024 * 1024;
  function signature(text) {
    if (typeof text !== 'string' || text.length > MAX_BYTES) throw new Error('INI must be no larger than 2 MiB.');
    let section = '', conditional = 0;
    const found = [];
    for (const line of text.replace(/^\uFEFF/, '').split(/\r?\n/)) {
      const stripped = line.trim();
      const directive = /^#\s*(if|ifdef|ifndef|endif)\b/i.exec(stripped);
      if (directive) {
        if (/^endif$/i.test(directive[1])) {
          if (--conditional < 0) throw new Error('Unbalanced INI conditional.');
        } else conditional++;
        continue;
      }
      const header = /^\[([^\]]+)\]\s*(?:;.*)?$/.exec(stripped);
      if (header) { section = header[1].trim().toLowerCase(); continue; }
      if (section !== 'tunerstudio' || !/^signature\s*=/i.test(stripped)) continue;
      if (conditional) throw new Error('Conditional signature is unsupported; enter it manually.');
      const match = /^signature\s*=\s*"([\x20-\x7e]{1,180})"\s*(?:;.*)?$/i.exec(stripped);
      if (!match || !match[1].startsWith('rusEFI ')) throw new Error('INI has an unsupported rusEFI signature.');
      found.push(match[1]);
    }
    if (conditional !== 0) throw new Error('Unbalanced INI conditional.');
    if (!found.length || found.some((value) => value !== found[0])) throw new Error('INI needs one unambiguous [TunerStudio] rusEFI signature.');
    return found[0];
  }
  function lookup(value) {
    // Restrict path components; custom branches or board names are left to
    // the official manual lookup instead of constructing ambiguous URLs.
    const match = /^rusEFI ([A-Za-z0-9_-]+)\.(\d{4})\.(\d{2})\.(\d{2})\.([A-Za-z0-9_-]+)\.(\d+)$/.exec(value);
    if (!match) return null;
    return 'https://rusefi.com/online/ini/rusefi/' + match.slice(1).join('/') + '.ini';
  }
  return { MAX_BYTES, signature, lookup };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = RusefiIni;
