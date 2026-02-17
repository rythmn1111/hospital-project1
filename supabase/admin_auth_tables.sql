-- Admin authentication tables for WhatsApp OTP login

CREATE TABLE admins (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  phone text UNIQUE NOT NULL,
  name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE admin_otps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  phone text NOT NULL,
  code text NOT NULL,
  expires_at timestamptz NOT NULL DEFAULT (now() + interval '5 minutes'),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Index for fast OTP lookups
CREATE INDEX idx_admin_otps_phone_code ON admin_otps (phone, code);

-- Example: Insert a test admin
-- INSERT INTO admins (phone, name) VALUES ('91XXXXXXXXXX', 'Test Admin');
