-- Wellbeing: nutrition, weight coaching, mental wellbeing, challenges and rewards.
-- Weigh-ins, steps, active minutes, blood pressure and questionnaire totals live in the shared
-- `observations` table (bioverse/vitals_codes.py); these tables hold everything else.

-- --- Nutrition -------------------------------------------------------------------------------------

-- Reference food list (per serving), from public USDA FoodData Central style values. Not patient data.
CREATE TABLE nutrition_foods (
    id              text PRIMARY KEY,                 -- stable slug, e.g. 'oatmeal-cooked'
    name            text NOT NULL,
    category        text NOT NULL,
    serving         text NOT NULL,                    -- '1 cup (234 g)'
    serving_grams   numeric NOT NULL CHECK (serving_grams > 0),
    kcal            numeric NOT NULL CHECK (kcal >= 0),
    protein_g       numeric NOT NULL CHECK (protein_g >= 0),
    carbs_g         numeric NOT NULL CHECK (carbs_g >= 0),
    fat_g           numeric NOT NULL CHECK (fat_g >= 0),
    fiber_g         numeric NOT NULL CHECK (fiber_g >= 0),
    sugar_g         numeric NOT NULL CHECK (sugar_g >= 0),
    sodium_mg       numeric NOT NULL CHECK (sodium_mg >= 0),
    veg_servings    numeric NOT NULL DEFAULT 0,       -- vegetable servings per serving (MyPlate cup-equivalents)
    water_ml        numeric NOT NULL DEFAULT 0,       -- plain drinks that count toward hydration
    aliases         text[] NOT NULL DEFAULT '{}',
    source          text NOT NULL DEFAULT 'USDA FoodData Central (rounded)'
);
CREATE INDEX nutrition_foods_name_idx ON nutrition_foods (lower(name));

-- NutritionIntake (FHIR R5): one meal. Items carry a copy of the nutrients so history never changes.
CREATE TABLE nutrition_intakes (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    eaten_on        date NOT NULL,
    meal            text NOT NULL CHECK (meal IN ('breakfast', 'lunch', 'dinner', 'snack')),
    source          text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'photo')),
    note            text,
    created_by      uuid REFERENCES users(id),
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX nutrition_intakes_patient_idx ON nutrition_intakes (patient_id, eaten_on DESC);

CREATE TABLE nutrition_intake_items (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id       uuid NOT NULL REFERENCES nutrition_intakes(id) ON DELETE CASCADE,
    patient_id      uuid NOT NULL REFERENCES patients(id),
    food_id         text NOT NULL REFERENCES nutrition_foods(id),
    name            text NOT NULL,
    servings        numeric NOT NULL CHECK (servings > 0 AND servings <= 20),
    kcal            numeric NOT NULL,
    protein_g       numeric NOT NULL,
    carbs_g         numeric NOT NULL,
    fat_g           numeric NOT NULL,
    fiber_g         numeric NOT NULL,
    sugar_g         numeric NOT NULL,
    sodium_mg       numeric NOT NULL,
    veg_servings    numeric NOT NULL DEFAULT 0,
    water_ml        numeric NOT NULL DEFAULT 0
);
CREATE INDEX nutrition_intake_items_intake_idx ON nutrition_intake_items (intake_id);

-- NutritionOrder-like per-patient overrides of the default daily targets, set by a clinician.
CREATE TABLE nutrition_targets (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    nutrient        text NOT NULL,
    value           numeric NOT NULL CHECK (value > 0),
    reason          text,
    practitioner_id uuid NOT NULL REFERENCES practitioners(id),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (patient_id, nutrient)
);

-- --- Weight coach -----------------------------------------------------------------------------------

-- QuestionnaireResponse: the gentle eating-disorder screen (SCOFF) taken before any weight goal.
CREATE TABLE weight_screenings (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    instrument      text NOT NULL DEFAULT 'scoff',
    answers         jsonb NOT NULL,
    score           integer NOT NULL,
    positive        boolean NOT NULL,
    review_item_id  uuid REFERENCES review_items(id),
    cleared_by      uuid REFERENCES users(id),       -- clinician who cleared coaching after a positive screen
    cleared_at      timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX weight_screenings_patient_idx ON weight_screenings (patient_id, created_at DESC);

-- Goal (FHIR Goal): target weight and pace. One active goal per patient.
CREATE TABLE weight_goals (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    start_weight_kg numeric NOT NULL CHECK (start_weight_kg > 0),
    target_weight_kg numeric NOT NULL CHECK (target_weight_kg > 0),
    pace_kg_week    numeric NOT NULL CHECK (pace_kg_week > 0 AND pace_kg_week <= 1),
    height_cm       numeric NOT NULL CHECK (height_cm > 0),
    screening_id    uuid NOT NULL REFERENCES weight_screenings(id),
    status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'achieved', 'stopped')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    ended_at        timestamptz
);
CREATE UNIQUE INDEX weight_goals_one_active ON weight_goals (patient_id) WHERE status = 'active';

-- The weekly check-in the coach job writes, one per goal per week.
CREATE TABLE weight_checkins (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    goal_id         uuid NOT NULL REFERENCES weight_goals(id) ON DELETE CASCADE,
    week_start      date NOT NULL,
    weekly_avg_kg   numeric,
    change_kg       numeric,
    percent_to_goal numeric,
    message         text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (goal_id, week_start)
);

-- --- Mental wellbeing -------------------------------------------------------------------------------

-- QuestionnaireResponse: PHQ-9 and GAD-7, with the item scores and the total also in `observations`.
CREATE TABLE mind_questionnaire_responses (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    instrument      text NOT NULL CHECK (instrument IN ('phq9', 'gad7')),
    items           integer[] NOT NULL,
    difficulty      text,
    total           integer NOT NULL,
    severity        text NOT NULL,
    item9           integer,                          -- PHQ-9 item 9, kept apart because it drives the crisis path
    crisis          boolean NOT NULL DEFAULT false,
    observation_id  uuid REFERENCES observations(id),
    review_item_id  uuid REFERENCES review_items(id),
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mind_responses_patient_idx ON mind_questionnaire_responses (patient_id, instrument, created_at DESC);

-- Patient-reported mood journal. Notes are private to the patient unless they choose to share.
CREATE TABLE mind_journal_entries (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    mood            integer NOT NULL CHECK (mood BETWEEN 1 AND 5),
    tags            text[] NOT NULL DEFAULT '{}',
    note            text,
    shared          boolean NOT NULL DEFAULT false,
    red_flag_level  text NOT NULL DEFAULT 'none',
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mind_journal_patient_idx ON mind_journal_entries (patient_id, created_at DESC);

CREATE TABLE mind_preferences (
    patient_id      uuid PRIMARY KEY REFERENCES patients(id),
    retest_reminders boolean NOT NULL DEFAULT false,
    retest_weeks    integer NOT NULL DEFAULT 4 CHECK (retest_weeks BETWEEN 2 AND 4),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- --- Challenges and rewards ---------------------------------------------------------------------------

CREATE TABLE challenge_definitions (
    id              text PRIMARY KEY,
    title           text NOT NULL,
    description     text NOT NULL,
    metric          text NOT NULL CHECK (metric IN ('steps', 'active_minutes', 'bp_logged', 'veg_servings', 'water_ml')),
    target          numeric NOT NULL CHECK (target > 0),
    unit            text NOT NULL,
    period          text NOT NULL CHECK (period IN ('day', 'week')),
    duration_days   integer NOT NULL CHECK (duration_days > 0),
    points          integer NOT NULL CHECK (points >= 0),     -- completion bonus
    points_per_period integer NOT NULL DEFAULT 10,    -- for each day (or week) the target is met
    family_allowed  boolean NOT NULL DEFAULT true,
    position        integer NOT NULL DEFAULT 100
);

-- A family challenge: several patients doing one challenge together. Everyone joins by their own choice.
CREATE TABLE challenge_teams (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    definition_id   text NOT NULL REFERENCES challenge_definitions(id),
    created_by      uuid NOT NULL REFERENCES patients(id),
    started_on      date NOT NULL,
    ends_on         date NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE challenge_team_members (
    team_id         uuid NOT NULL REFERENCES challenge_teams(id) ON DELETE CASCADE,
    patient_id      uuid NOT NULL REFERENCES patients(id),
    status          text NOT NULL DEFAULT 'invited' CHECK (status IN ('invited', 'joined', 'declined', 'left')),
    invited_by      uuid REFERENCES patients(id),
    responded_at    timestamptz,
    PRIMARY KEY (team_id, patient_id)
);

CREATE TABLE challenge_enrollments (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    definition_id   text NOT NULL REFERENCES challenge_definitions(id),
    team_id         uuid REFERENCES challenge_teams(id),
    started_on      date NOT NULL,
    ends_on         date NOT NULL,
    status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'ended', 'left')),
    periods_met     integer NOT NULL DEFAULT 0,
    current_streak  integer NOT NULL DEFAULT 0,
    best_streak     integer NOT NULL DEFAULT 0,
    last_synced_at  timestamptz,
    completed_at    timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX challenge_enrollments_one_active ON challenge_enrollments (patient_id, definition_id)
    WHERE status = 'active';

-- Points are a ledger: the balance is the sum. dedupe_key keeps every award idempotent.
CREATE TABLE challenge_points (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    delta           integer NOT NULL,
    reason          text NOT NULL,
    enrollment_id   uuid REFERENCES challenge_enrollments(id),
    dedupe_key      text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (patient_id, dedupe_key)
);

CREATE TABLE challenge_badges (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    badge           text NOT NULL,
    title           text NOT NULL,
    enrollment_id   uuid REFERENCES challenge_enrollments(id),
    awarded_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (patient_id, badge)
);

-- Clearly fictional demo perks.
CREATE TABLE challenge_rewards (
    id              text PRIMARY KEY,
    title           text NOT NULL,
    description     text NOT NULL,
    cost            integer NOT NULL CHECK (cost > 0),
    active          boolean NOT NULL DEFAULT true,
    position        integer NOT NULL DEFAULT 100
);

CREATE TABLE challenge_redemptions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      uuid NOT NULL REFERENCES patients(id),
    reward_id       text NOT NULL REFERENCES challenge_rewards(id),
    points          integer NOT NULL,
    code            text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX challenge_redemptions_patient_idx ON challenge_redemptions (patient_id, created_at DESC);
