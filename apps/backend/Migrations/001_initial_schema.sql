-- Initial database schema
-- Applied by: DevOps Agentic Teammates

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(200) NOT NULL,
    description VARCHAR(2000),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ
);

CREATE INDEX idx_items_name ON items(name);
CREATE INDEX idx_items_created_at ON items(created_at DESC);
CREATE INDEX idx_items_active ON items(is_active) WHERE is_active = true;
