-- ─── 011: manual AP grouping — several BSSIDs shown as one box on the floor map ──

ALTER TABLE access_points ADD COLUMN IF NOT EXISTS group_name VARCHAR(255);
CREATE INDEX IF NOT EXISTS idx_access_points_group_name ON access_points (group_name);
