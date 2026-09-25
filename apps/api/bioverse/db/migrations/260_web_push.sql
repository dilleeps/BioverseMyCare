-- Background Web Push: one row per browser or installed app that has turned on push (bioverse/webpush.py).
--
-- The endpoint is a capability URL issued by the browser's push service (Google, Mozilla, Apple, Microsoft).
-- p256dh and auth are the browser's public key and secret used to encrypt each message (RFC 8291).
-- An endpoint belongs to one user: when someone else signs in on the same device and turns push on,
-- the row moves to them.
CREATE TABLE push_subscriptions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint        text NOT NULL UNIQUE,
    p256dh          text NOT NULL,
    auth            text NOT NULL,
    user_agent      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    last_success_at timestamptz,
    failure_count   integer NOT NULL DEFAULT 0
);
CREATE INDEX push_subscriptions_user_idx ON push_subscriptions (user_id);
