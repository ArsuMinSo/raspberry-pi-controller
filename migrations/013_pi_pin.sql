-- ─── 013: manual Pi position pin (spring-layout mode — everything floats unless pinned) ──

ALTER TABLE raspberries ADD COLUMN IF NOT EXISTS pinned_x DOUBLE PRECISION;
ALTER TABLE raspberries ADD COLUMN IF NOT EXISTS pinned_y DOUBLE PRECISION;
