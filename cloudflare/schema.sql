-- Keep report metadata and the signed envelope in one atomic CAS row.
-- Do not drop this row after clients have applied a pack: sequence is monotonic.
CREATE TABLE IF NOT EXISTS validation_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  sequence INTEGER NOT NULL CHECK (sequence >= 0),
  reports TEXT NOT NULL,
  envelope TEXT
);
INSERT OR IGNORE INTO validation_state (id, sequence, reports, envelope)
VALUES (1, 0, '[]', NULL);
