-- ─── 014: floor map view settings shared across users (e.g. floor-plan background visibility) ──

CREATE TABLE IF NOT EXISTS floor_map_settings (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    plan_visible BOOLEAN NOT NULL DEFAULT TRUE
);

INSERT INTO floor_map_settings (id, plan_visible) VALUES (1, TRUE) ON CONFLICT (id) DO NOTHING;
