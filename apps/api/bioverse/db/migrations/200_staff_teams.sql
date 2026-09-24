-- Staff work in different teams (front desk, pharmacy) that need different screens and alerts.
-- NULL means no team: the person sees everything their role allows.
ALTER TABLE users ADD COLUMN team text CHECK (team IN ('front_desk', 'pharmacy'));
