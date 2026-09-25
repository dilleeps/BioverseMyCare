-- A cancelled appointment frees its slot, so another patient must be able to book it:
-- only one *active* appointment per slot.
ALTER TABLE appointments DROP CONSTRAINT appointments_slot_id_key;
CREATE UNIQUE INDEX appointments_active_slot_key ON appointments (slot_id) WHERE status <> 'cancelled';
