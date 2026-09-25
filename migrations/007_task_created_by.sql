-- ─── 007: track task creator separately from last editor ───────────────
-- owner_user_id already tracks "last edited by" (used for run attribution).
-- Add created_by_user_id, set once at creation, never updated afterward.

ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS created_by_user_id INTEGER REFERENCES users (id);

-- Backfill: best available guess for existing rows is the current owner.
UPDATE scheduled_tasks SET created_by_user_id = owner_user_id WHERE created_by_user_id IS NULL;
