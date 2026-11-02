# The in-app help and reference module

GuzziOnBoard ships a self-contained help system: every workspace, tool, wire
protocol, ECU family, checksum concept and workshop workflow, searchable from
anywhere in the program.

- **Help menu** (menu bar) and **Help & guides** (sidebar, section 06).
- **`Ctrl`/`Cmd` + `K`** opens the global search spotlight over guides, tools,
  menu commands, protocols, glossary terms, the live ECU catalog and the bundled
  XDF library.
- **`F1`** opens the help center at the article you last read.
- Every article has a shareable permalink: `#help/<topic>`, `#help/tool/<id>`,
  `#help/protocol/<id>`, `#help/ecu/<id>`, `#help/xdf/<filename>` and
  `#help/glossary/<term>`.

## Files

| File | Role |
| --- | --- |
| `web/help-content.js` | All prose and data. Plain `window.GOB_HELP` object: categories, topics, tools, protocols, glossary, ECU family notes. No logic. |
| `web/help-module.js` | Search index, scoring, routing/hash handling, article rendering, the spotlight, and the generated ECU/XDF/tool-directory blocks. |
| `web/index.html` | `#help` workspace, `#helpSpotlightModal`, the Help menu and the menu-bar search chip. |
| `web/styles.css` | Section 17: help layout, tables, cards, spotlight, light-theme and print rules. |
| `tests/browser/help-center.spec.mjs` | Browser behaviour: search, deep links, jumps, spotlight keyboard control, generated explorers. |
| `tests/test_help_module.py` | Content integrity: unique ids, resolvable internal links, verbatim safety acknowledgements, geometry cross-checks against the catalog. |

## Adding an article

1. Append a topic object to one of the `TOPICS` blocks in `web/help-content.js`:

   ```js
   {
     id: 'howto-my-workflow',            // stable slug, used in #help/<id>
     title: 'How-to: do the thing',
     category: 'howto',                  // howto | tools | protocols | ecus | checksums | safety | glossary
     summary: 'One sentence that search shows.',
     tags: ['thing', 'workflow'],        // extra search words
     related: ['topic/howto-first-connection', 'protocol-kwp2000'],
     tools: [{ label: 'Open the panel', view: 'firmware', selector: '#mapsCard' }],
     body: `<h3>Steps</h3><ol><li>…</li></ol>`,   // trusted HTML, authored in this file
   }
   ```

2. `body` is rendered as-is, so it may use `help-table`, `gate-card warn`,
   `code`, `pre`, `kbd` and ordinary headings. Do not interpolate user data.
3. Add a jump button spec if the article describes a panel: `view` is a
   `data-view` id; `selector` is a CSS selector inside that view;
   `openDetails` expands a collapsed `<details>` first.
4. Run `pytest tests/test_help_module.py` — it fails on duplicate ids, broken
   `#help/...` links and unknown tool selectors.

## Adding a tool or protocol entry

Tool entries live in the `TOOLS` array (`id`, `name`, `category`, `view`,
`selector`, `summary`, `steps`, optional `caution`, `tags`). They are indexed
individually, rendered at `#help/tool/<id>`, and listed in the generated
directory at `#help/tools-directory`. Protocol entries live in `PROTOCOLS` and
render a specification table from `transport`, `baud`, `init`, `addressing`,
`framing` and `checksum`.

## How search works

The index is rebuilt lazily and after the catalog/XDF data arrives:

- guide topics (title, tags, summary, body text),
- tool entries and their steps,
- protocol articles and their specification fields,
- glossary terms,
- menu commands (clicking a result runs the command),
- panels not covered by a tool entry (clicking scrolls to the panel),
- every `/api/catalog` ECU and every `/api/maps` XDF definition.

A query is tokenised; a result must contain **every** token in some field.
Scores weight title > tags > summary > body, with a bonus for an exact phrase or
a title prefix. Results are highlighted with `<mark>` and a snippet from the
first match.

## Checks the test suite enforces

- scripts load in the order `help-content.js` → `help-module.js`, after `app.js`;
- every `data-help-topic` in the page names a real article;
- every internal `#help/...` reference and every `related` id resolves;
- the four safety acknowledgement strings quoted in the help are byte-identical
  to `SafetyGate.PROGRAMMING_ACKNOWLEDGEMENT`,
  `SafetyGate.UNVERIFIED_WRITER_ACKNOWLEDGEMENT`,
  `ProgrammingService.EXTERNAL_BACKUP_ACKNOWLEDGEMENT` and
  `TUNING_ACKNOWLEDGEMENT`;
- the IAW 5AM geometry quoted in the guides (0x4000, 0x4C000, 311,296 and
  327,680 bytes) matches `catalog/ecus/5am.json`;
- the browser suite checks that the tool directory lists exactly
  `GOB_HELP.tools.length` cards, once each, and that the glossary lists every
  term.
