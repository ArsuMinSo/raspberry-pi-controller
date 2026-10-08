-- ─── 017: APs can be pinned — fixed for the untangle layout, independent of having coordinates ───

ALTER TABLE access_points ADD COLUMN IF NOT EXISTS pinned BOOLEAN NOT NULL DEFAULT FALSE;
