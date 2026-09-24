-- In-hospital wayfinding: indoor maps, a walkable graph, and closures.
-- Additive only: new tables. The shared `locations` and `departments` tables are linked through
-- wf_location_nodes and never altered.
--
-- Coordinates are meters on each floor's plan: x grows to the right (east), y grows downward (south),
-- the same orientation the SVG plan is drawn in. Angles are degrees clockwise from east in that frame
-- (0 = east, 90 = south, 180 = west, 270 = north).

CREATE TABLE wf_buildings (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    name            text NOT NULL,
    campus          text,
    address         text,
    parking_note    text,                       -- shown when parking is the start or the destination
    help_note       text,                       -- where to get help when there is no route
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, name)
);

CREATE TABLE wf_floors (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    building_id     uuid NOT NULL REFERENCES wf_buildings(id) ON DELETE CASCADE,
    level           integer NOT NULL,           -- 0 is the parking level, 1 is the street level
    name            text NOT NULL,              -- "Level 1"
    short_name      text NOT NULL,              -- "1", shown on the floor switcher and in elevators
    width_m         numeric(6, 1) NOT NULL CHECK (width_m > 0),
    height_m        numeric(6, 1) NOT NULL CHECK (height_m > 0),
    UNIQUE (building_id, level)
);

-- Graph vertices. `code` is printed on "You are here" signs and opens /find-your-way?from=<code>.
CREATE TABLE wf_nodes (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    floor_id        uuid NOT NULL REFERENCES wf_floors(id) ON DELETE CASCADE,
    kind            text NOT NULL CHECK (kind IN
                        ('junction', 'door', 'entrance', 'elevator', 'stairs', 'escalator', 'desk', 'parking')),
    name            text,
    code            text UNIQUE CHECK (code ~ '^[A-Z0-9-]{3,32}$'),
    x               numeric(6, 1) NOT NULL,
    y               numeric(6, 1) NOT NULL,
    facing_deg      numeric(5, 1) CHECK (facing_deg >= 0 AND facing_deg < 360)  -- which way you face reading its sign
);
CREATE INDEX wf_nodes_floor_idx ON wf_nodes (floor_id);

-- Rooms and zones. polygon: [[x, y], ...] in floor meters. node_id is the door you walk to.
CREATE TABLE wf_areas (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    building_id     uuid NOT NULL REFERENCES wf_buildings(id) ON DELETE CASCADE,
    floor_id        uuid NOT NULL REFERENCES wf_floors(id) ON DELETE CASCADE,
    name            text NOT NULL,
    label           text,                       -- short label drawn on the plan
    kind            text NOT NULL CHECK (kind IN
                        ('clinic', 'lab', 'imaging', 'pharmacy', 'restroom', 'cafe', 'waiting', 'desk',
                         'elevator', 'stairs', 'escalator', 'entrance', 'parking', 'corridor')),
    polygon         jsonb NOT NULL CHECK (jsonb_typeof(polygon) = 'array' AND jsonb_array_length(polygon) >= 3),
    label_x         numeric(6, 1),              -- where the label sits; the polygon's centre when NULL
    label_y         numeric(6, 1),
    node_id        uuid REFERENCES wf_nodes(id),
    slug            text CHECK (slug ~ '^[a-z0-9-]{2,40}$'),
    keywords        text[] NOT NULL DEFAULT '{}',
    searchable      boolean NOT NULL DEFAULT true,
    UNIQUE (building_id, slug)
);
CREATE INDEX wf_areas_floor_idx ON wf_areas (floor_id);

-- Walkable connections, used in both directions. `segment` groups edges staff close together
-- ("Elevator A", "Level 1 corridor, east"). `closed` mirrors the active wf_closures row.
CREATE TABLE wf_edges (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    building_id     uuid NOT NULL REFERENCES wf_buildings(id) ON DELETE CASCADE,
    from_node       uuid NOT NULL REFERENCES wf_nodes(id) ON DELETE CASCADE,
    to_node         uuid NOT NULL REFERENCES wf_nodes(id) ON DELETE CASCADE,
    meters          numeric(6, 1) NOT NULL CHECK (meters > 0),
    step_free       boolean NOT NULL DEFAULT true,
    kind            text NOT NULL DEFAULT 'walk' CHECK (kind IN ('walk', 'elevator', 'stairs', 'escalator')),
    segment         text,
    closed          boolean NOT NULL DEFAULT false,
    closed_reason   text,
    closed_at       timestamptz,
    CHECK (from_node <> to_node),
    CHECK (kind = 'walk' OR kind = 'elevator' OR NOT step_free),   -- stairs and escalators are never step-free
    CHECK (NOT closed OR closed_reason IS NOT NULL),
    UNIQUE (from_node, to_node)
);
CREATE INDEX wf_edges_building_idx ON wf_edges (building_id);
CREATE INDEX wf_edges_segment_idx ON wf_edges (building_id, segment);

-- Closure log: who closed what, why, and when it reopened. One active closure per segment.
CREATE TABLE wf_closures (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    building_id     uuid NOT NULL REFERENCES wf_buildings(id) ON DELETE CASCADE,
    segment         text,
    edge_ids        uuid[] NOT NULL CHECK (cardinality(edge_ids) > 0),
    reason          text NOT NULL,
    closed_by       uuid REFERENCES users(id),
    closed_at       timestamptz NOT NULL DEFAULT clock_timestamp(),
    reopened_by     uuid REFERENCES users(id),
    reopened_at     timestamptz
);
CREATE INDEX wf_closures_building_idx ON wf_closures (building_id, closed_at DESC);
CREATE UNIQUE INDEX wf_closures_active_segment_idx ON wf_closures (building_id, segment)
    WHERE reopened_at IS NULL AND segment IS NOT NULL;

-- Shared locations, departments and specialties -> the desk a patient walks to.
-- Resolution for an appointment: department at the practitioner's location, then location + specialty,
-- then location, then specialty.
CREATE TABLE wf_location_nodes (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    building_id     uuid NOT NULL REFERENCES wf_buildings(id) ON DELETE CASCADE,
    location_id     uuid REFERENCES locations(id),
    department_id   uuid REFERENCES departments(id),
    specialty       text,
    node_id         uuid NOT NULL REFERENCES wf_nodes(id),
    area_id         uuid REFERENCES wf_areas(id),
    CHECK (location_id IS NOT NULL OR department_id IS NOT NULL OR specialty IS NOT NULL)
);
CREATE INDEX wf_location_nodes_org_idx ON wf_location_nodes (organization_id);
