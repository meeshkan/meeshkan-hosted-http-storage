CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

DROP TABLE IF EXISTS http_data;
CREATE TABLE http_data (
  http_data_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  claim_uuid UUID NULL,
  created TIMESTAMP DEFAULT NOW(),
  json_data JSONB
);

DROP TABLE IF EXISTS http_claimed_uuid;
CREATE TABLE http_claimed_uuid (
  claim_uuid UUID PRIMARY KEY,
  user_id TEXT NOT NULL
);
