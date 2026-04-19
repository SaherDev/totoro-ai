-- legacy_places_seed.sql — feature 019 migration verification fixture (T057)
--
-- 20+ representative legacy-schema rows for testing the Phase 6 migration.
-- Apply against a DB at pre-feature-019 head (`2d4472dd48a1`) before running
-- scripts/seed_migration.py + alembic upgrade head.
--
-- Row distribution (per T057):
--   * 5 with cuisine
--   * 5 with price_range (low/mid/high, plus 1 legitimately unmapped)
--   * 5 with lat/lng/address AND external_provider+external_id (→ Redis geo seed)
--   * 3 with lat/lng/address but NO external_id (→ lost-geo log lines)
--   * 3 with no relocatable data (place_name only → defaulted to services)
-- Several rows intentionally overlap categories so the 20 total covers everything.

-- Wipe existing test data (keep alembic_version and everything else intact).
DELETE FROM embeddings WHERE place_id IN (SELECT id FROM places);
DELETE FROM interaction_log WHERE place_id IS NOT NULL;
DELETE FROM places;

-- Rows 1–5: cuisine set, with geo + external_id (→ food_and_drink, geo seeded)
INSERT INTO places (id, user_id, place_name, address, cuisine, price_range, lat, lng, source_url, source, external_provider, external_id, ambiance, created_at, updated_at)
VALUES
  ('10000000-0000-0000-0000-000000000001', 'test-user-1', 'Sushi Sora', '123 Tokyo St', 'japanese', 'high', 35.6895, 139.6917, 'https://example.com/sushisora', 'llm_ner', 'google', 'ChIJTEST0001', 'upscale', NOW(), NOW()),
  ('10000000-0000-0000-0000-000000000002', 'test-user-1', 'Pasta Roma', '45 Rome Ave', 'italian', 'mid', 41.9028, 12.4964, 'https://example.com/pasta', 'llm_ner', 'google', 'ChIJTEST0002', 'cozy', NOW(), NOW()),
  ('10000000-0000-0000-0000-000000000003', 'test-user-2', 'Pad Thai Palace', '7 Bangkok Rd', 'thai', 'low', 13.7563, 100.5018, NULL, 'manual', 'google', 'ChIJTEST0003', 'casual', NOW(), NOW()),
  ('10000000-0000-0000-0000-000000000004', 'test-user-2', 'Kimchi House', '9 Seoul Way', 'korean', 'mid', 37.5665, 126.9780, NULL, 'llm_ner', 'google', 'ChIJTEST0004', NULL, NOW(), NOW()),
  ('10000000-0000-0000-0000-000000000005', 'test-user-3', 'Taco Libre', '200 Mexico Plaza', 'mexican', 'low', 19.4326, -99.1332, NULL, 'subtitle_check', 'google', 'ChIJTEST0005', 'lively', NOW(), NOW());

-- Rows 6–7: extra price_range coverage with a legitimately unmapped value
INSERT INTO places (id, user_id, place_name, address, cuisine, price_range, lat, lng, source_url, source, external_provider, external_id, ambiance, created_at, updated_at)
VALUES
  ('10000000-0000-0000-0000-000000000006', 'test-user-3', 'Burger Joint', '15 Main St', NULL, 'low', NULL, NULL, NULL, 'manual', 'google', 'ChIJTEST0006', NULL, NOW(), NOW()),
  ('10000000-0000-0000-0000-000000000007', 'test-user-3', 'Mystery Bistro', '1 Mystery Ln', NULL, 'premium', NULL, NULL, NULL, 'manual', 'google', 'ChIJTEST0007', NULL, NOW(), NOW());

-- Rows 8–10: lat/lng/address BUT missing external_id → geo_lost_no_pid log
INSERT INTO places (id, user_id, place_name, address, cuisine, price_range, lat, lng, source_url, source, external_provider, external_id, ambiance, created_at, updated_at)
VALUES
  ('10000000-0000-0000-0000-000000000008', 'test-user-4', 'No-ID Cafe', '88 Anon St', 'coffee', NULL, 48.8566, 2.3522, NULL, 'manual', '', NULL, NULL, NOW(), NOW()),
  ('10000000-0000-0000-0000-000000000009', 'test-user-4', 'Orphan Diner', '12 Lost Rd', NULL, NULL, 34.0522, -118.2437, NULL, 'manual', '', NULL, NULL, NOW(), NOW()),
  ('10000000-0000-0000-0000-000000000010', 'test-user-5', 'Stray Sushi', '99 Drift Ln', 'japanese', NULL, 40.7128, -74.0060, NULL, 'manual', '', NULL, NULL, NOW(), NOW());

-- Rows 11–13: no relocatable data (no cuisine, no price_range, no geo) → services-defaulted
INSERT INTO places (id, user_id, place_name, address, cuisine, price_range, lat, lng, source_url, source, external_provider, external_id, ambiance, created_at, updated_at)
VALUES
  ('10000000-0000-0000-0000-000000000011', 'test-user-5', 'Quiet Corner', '33 Silent Ave', NULL, NULL, NULL, NULL, NULL, 'manual', 'google', 'ChIJTEST0011', NULL, NOW(), NOW()),
  ('10000000-0000-0000-0000-000000000012', 'test-user-5', 'Forgotten Spot', '77 Memory Lane', NULL, NULL, NULL, NULL, NULL, 'manual', 'google', 'ChIJTEST0012', NULL, NOW(), NOW()),
  ('10000000-0000-0000-0000-000000000013', 'test-user-6', 'Empty Plate', '4 Bare St', NULL, NULL, NULL, NULL, NULL, 'manual', 'google', 'ChIJTEST0013', NULL, NOW(), NOW());

-- Rows 14–16: things_to_do keyword matches in place_name (museum, park, temple)
INSERT INTO places (id, user_id, place_name, address, cuisine, price_range, lat, lng, source_url, source, external_provider, external_id, ambiance, created_at, updated_at)
VALUES
  ('10000000-0000-0000-0000-000000000014', 'test-user-6', 'Tokyo National Museum', '13 Ueno Park', NULL, NULL, 35.7188, 139.7765, NULL, 'manual', 'google', 'ChIJTEST0014', NULL, NOW(), NOW()),
  ('10000000-0000-0000-0000-000000000015', 'test-user-6', 'Lumphini Park', '200 Rama IV Rd', NULL, NULL, 13.7307, 100.5418, NULL, 'manual', 'google', 'ChIJTEST0015', NULL, NOW(), NOW()),
  ('10000000-0000-0000-0000-000000000016', 'test-user-7', 'Wat Pho Temple', '2 Sanamchai Rd', NULL, NULL, 13.7465, 100.4927, NULL, 'manual', 'google', 'ChIJTEST0016', NULL, NOW(), NOW());

-- Rows 17–20: additional cuisine + price_range + geo coverage to pad the fixture past 20
INSERT INTO places (id, user_id, place_name, address, cuisine, price_range, lat, lng, source_url, source, external_provider, external_id, ambiance, created_at, updated_at)
VALUES
  ('10000000-0000-0000-0000-000000000017', 'test-user-7', 'Dim Sum Corner', '88 HK Plaza', 'chinese', 'mid', 22.3193, 114.1694, NULL, 'llm_ner', 'google', 'ChIJTEST0017', NULL, NOW(), NOW()),
  ('10000000-0000-0000-0000-000000000018', 'test-user-7', 'Falafel Express', '12 Istanbul Sq', 'middle-eastern', 'low', 41.0082, 28.9784, NULL, 'llm_ner', 'google', 'ChIJTEST0018', NULL, NOW(), NOW()),
  ('10000000-0000-0000-0000-000000000019', 'test-user-8', 'Curry Leaf', '5 Mumbai St', 'indian', 'mid', 19.0760, 72.8777, NULL, 'llm_ner', 'google', 'ChIJTEST0019', 'casual', NOW(), NOW()),
  ('10000000-0000-0000-0000-000000000020', 'test-user-8', 'Ramen Ichiban', '7 Osaka Alley', 'japanese', 'high', 34.6937, 135.5023, NULL, 'llm_ner', 'google', 'ChIJTEST0020', 'lively', NOW(), NOW());

-- Sanity check: 20 total rows
-- SELECT COUNT(*) FROM places;
