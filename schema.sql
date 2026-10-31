-- =============================================================================
-- MOHERA Perfume Website - Database Schema
-- Compatible with PostgreSQL (Neon DB / Supabase / AWS RDS / Local Postgres)
-- =============================================================================

-- 1. Users Table
-- Stores customer and user profiles with hashed passwords
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    phone VARCHAR(40) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    email_verified_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users (LOWER(email));

-- 2. Email OTPs Table
-- Stores 4-digit verification codes, hashes, attempt limits, and expiration
CREATE TABLE IF NOT EXISTS email_otps (
    id BIGSERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    otp_hash VARCHAR(255) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    verified_at TIMESTAMPTZ,
    attempts INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_email_otps_email_created_at ON email_otps (LOWER(email), created_at DESC);

-- 3. Customer Enquiries Table
-- Stores contact queries and custom fragrance enquiries from the frontend
CREATE TABLE IF NOT EXISTS enquiries (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    email VARCHAR(255) NOT NULL,
    phone VARCHAR(40) NOT NULL,
    enquiry TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'new',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_enquiries_email ON enquiries (LOWER(email));
CREATE INDEX IF NOT EXISTS idx_enquiries_status ON enquiries (status);

-- 4. Admins Table
-- Stores admin accounts and credentials
CREATE TABLE IF NOT EXISTS admins (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'admin',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_admins_username ON admins (LOWER(username));

-- 5. Order Head Table
-- Stores customer order summary / header
CREATE TABLE IF NOT EXISTS order_head (
    id SERIAL PRIMARY KEY,
    customer_name VARCHAR(160) NOT NULL,
    phone VARCHAR(40) NOT NULL,
    email VARCHAR(255) NOT NULL,
    address TEXT NOT NULL,
    order_type VARCHAR(20) NOT NULL DEFAULT 'online'
        CHECK (order_type IN ('online', 'offline')),
    total_price NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    payment_mode VARCHAR(50) NOT NULL,
    payment_status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (payment_status IN ('success', 'cancel', 'failed')),
    paid_status SMALLINT NOT NULL DEFAULT 0
        CHECK (paid_status IN (0, 1)),
    order_datetime TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_order_head_email ON order_head (LOWER(email));
CREATE INDEX IF NOT EXISTS idx_order_head_status ON order_head (payment_status);
CREATE INDEX IF NOT EXISTS idx_order_head_datetime ON order_head (order_datetime DESC);

-- 6. Order Details Table
-- Stores individual line items for each order
CREATE TABLE IF NOT EXISTS order_details (
    id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES order_head(id) ON DELETE CASCADE,
    product_name VARCHAR(255) NOT NULL,
    quantity INT NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price NUMERIC(10, 2) NOT NULL,
    total_price NUMERIC(10, 2) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_order_details_order_id ON order_details (order_id);

-- Optional trigger function to auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION trigger_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'set_timestamp_users'
    ) THEN
        CREATE TRIGGER set_timestamp_users
        BEFORE UPDATE ON users
        FOR EACH ROW
        EXECUTE FUNCTION trigger_set_timestamp();
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'set_timestamp_enquiries'
    ) THEN
        CREATE TRIGGER set_timestamp_enquiries
        BEFORE UPDATE ON enquiries
        FOR EACH ROW
        EXECUTE FUNCTION trigger_set_timestamp();
    END IF;
END $$;
