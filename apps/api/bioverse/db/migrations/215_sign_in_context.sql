-- What a sign-in was started with (e.g. an invite token), carried through the OIDC round trip.
ALTER TABLE oidc_login_requests ADD COLUMN context jsonb NOT NULL DEFAULT '{}';
