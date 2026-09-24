"""Wellbeing demo data (IDs 13000-13999). Idempotent. All data is fictional.

- The food list, challenge catalog and demo rewards (upserted every run).
- Maya: ten days of meals where sodium is often high (her record shows raised blood pressure), a height and
  four weekly weigh-ins with a steady weight-loss goal, two mild PHQ-9 and GAD-7 results with retest
  reminders on, a few mood journal entries, an active steps challenge on a streak, a completed hydration
  challenge, points, badges and one redeemed demo perk.
"""

from __future__ import annotations

from datetime import timedelta

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from bioverse.challenge_engine import BADGES, seed_catalog, sync_enrollment
from bioverse.db.seeds.context import SeedContext
from bioverse.db.seeds.ids import P_MAYA, _id
from bioverse.mind_instruments import INSTRUMENTS, score
from bioverse.nutrition_data import FOOD_FIELDS, FOODS, NUTRIENTS
from bioverse.vitals_codes import CODES

HEIGHT_OBS = _id(13001)
WEIGHT_OBS = [_id(13010 + i) for i in range(4)]
SCREENING, GOAL = _id(13020), _id(13021)
STEPS_ENROLLMENT, HYDRATION_ENROLLMENT = _id(13040), _id(13041)
REDEMPTION = _id(13060)

# Ten days of meals, oldest first, ending yesterday. Takeout, deli and canned food push sodium up most days.
MENUS = [
    {"breakfast": [("bagel-plain", 1), ("cream-cheese", 1), ("coffee-black", 1)],
     "lunch": [("turkey-sandwich", 1), ("potato-chips", 1), ("apple", 1)],
     "dinner": [("spaghetti-meat-sauce", 1), ("side-salad-ranch", 1)],
     "snack": [("pretzels", 1)]},
    {"breakfast": [("oatmeal-cooked", 1), ("blueberries", 0.5), ("coffee-black", 1)],
     "lunch": [("chicken-noodle-soup", 1.5), ("saltine-crackers", 1), ("string-cheese", 1)],
     "dinner": [("rotisserie-chicken", 1), ("mashed-potatoes", 1), ("green-beans", 1)],
     "snack": [("greek-yogurt", 1)]},
    {"breakfast": [("breakfast-sandwich", 1), ("orange-juice", 1)],
     "lunch": [("chicken-caesar-salad", 1)],
     "dinner": [("cheese-pizza", 2), ("side-salad-ranch", 1)],
     "snack": [("dark-chocolate", 1)]},
    {"breakfast": [("greek-yogurt", 1), ("granola", 1), ("banana", 1)],
     "lunch": [("ham-cheese-sandwich", 1), ("dill-pickle", 1)],
     "dinner": [("salmon-baked", 1.5), ("brown-rice", 1), ("broccoli-cooked", 2)],
     "snack": [("almonds", 1)]},
    {"breakfast": [("eggs-scrambled", 1), ("whole-wheat-bread", 2), ("butter", 0.5)],
     "lunch": [("instant-ramen", 1), ("edamame", 1)],
     "dinner": [("chicken-stir-fry-rice", 1)],
     "snack": [("popcorn-butter", 1)]},
    {"breakfast": [("oatmeal-cooked", 1), ("banana", 1), ("coffee-black", 1)],
     "lunch": [("chicken-garden-salad", 1), ("pita-whole-wheat", 1)],
     "dinner": [("beef-tacos", 1), ("rice-and-beans", 1), ("salsa", 1)],
     "snack": [("apple", 1), ("peanut-butter", 1)]},
    {"breakfast": [("bagel-plain", 1), ("cream-cheese", 1), ("coffee-black", 1)],
     "lunch": [("chicken-burrito-bowl", 1)],
     "dinner": [("lasagna-frozen", 1), ("mixed-greens", 1)],
     "snack": [("string-cheese", 1)]},
    {"breakfast": [("greek-yogurt", 1), ("strawberries", 1), ("granola", 0.5)],
     "lunch": [("tomato-soup", 1), ("grilled-cheese", 1)],
     "dinner": [("chicken-breast", 1.5), ("baked-potato", 1), ("broccoli-cooked", 2), ("butter", 1)],
     "snack": [("trail-mix", 1)]},
    {"breakfast": [("breakfast-sandwich", 1), ("coffee-black", 1)],
     "lunch": [("turkey-sandwich", 1), ("potato-chips", 1)],
     "dinner": [("chili-with-beans", 1.5), ("cornbread", 1), ("side-salad-ranch", 1)],
     "snack": [("pretzels", 1)]},
    {"breakfast": [("oatmeal-cooked", 1), ("blueberries", 1), ("coffee-black", 1)],
     "lunch": [("chicken-caesar-salad", 1), ("water-bottle", 1)],
     "dinner": [("pork-chop", 1), ("sweet-potato", 1), ("green-beans", 2)],
     "snack": [("pear", 1)]},
]
MEAL_TIMES = {"breakfast": 0, "lunch": 1, "dinner": 2, "snack": 3}


def run(conn, ctx: SeedContext) -> None:
    _reference(conn)
    _meals(conn, ctx)
    _weight(conn, ctx)
    _mind(conn, ctx)
    _challenges(conn, ctx)


def _reference(conn) -> None:
    cols = ", ".join(FOOD_FIELDS)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in FOOD_FIELDS if c != "id")
    conn.cursor().executemany(
        f"INSERT INTO nutrition_foods ({cols}) VALUES ({', '.join(['%s'] * len(FOOD_FIELDS))}) "
        f"ON CONFLICT (id) DO UPDATE SET {updates}",
        [tuple(f[c] for c in FOOD_FIELDS) for f in FOODS],
    )
    seed_catalog(conn)


def _meals(conn, ctx: SeedContext) -> None:
    foods = {f["id"]: f for f in FOODS}
    for d, menu in enumerate(MENUS):
        day = ctx.days(-len(MENUS) + d)
        for meal, items in menu.items():
            meal_id = _id(13100 + d * 4 + MEAL_TIMES[meal])
            hh = {"breakfast": 8, "lunch": 12, "dinner": 19, "snack": 15}[meal]
            new = conn.execute(
                """
                INSERT INTO nutrition_intakes (id, patient_id, eaten_on, meal, source, created_at)
                VALUES (%s, %s, %s, %s, 'manual', %s) ON CONFLICT DO NOTHING RETURNING id
                """,
                (meal_id, P_MAYA, day, meal, ctx.at(day, hh, 30)),
            ).fetchone()
            if not new:
                continue
            for food_id, servings in items:
                f = foods[food_id]
                conn.execute(
                    f"""
                    INSERT INTO nutrition_intake_items (intake_id, patient_id, food_id, name, servings, {", ".join(NUTRIENTS)})
                    VALUES (%s, %s, %s, %s, %s, {", ".join(["%s"] * len(NUTRIENTS))})
                    """,
                    (meal_id, P_MAYA, food_id, f["name"], servings, *[round(f[n] * servings, 2) for n in NUTRIENTS]),
                )


def _weight(conn, ctx: SeedContext) -> None:
    h, w = CODES["height"], CODES["weight"]
    conn.execute(
        """
        INSERT INTO observations (id, patient_id, loinc_code, display, value, unit, interpretation, effective_at, category, source)
        VALUES (%s, %s, %s, %s, 165, %s, 'N', %s, 'vital-signs', 'clinic') ON CONFLICT DO NOTHING
        """,
        (HEIGHT_OBS, P_MAYA, h.loinc, h.display, h.unit, ctx.at(ctx.days(-194), 9)),
    )
    for i, (days_ago, kg) in enumerate([(22, 79.2), (15, 78.8), (8, 78.3), (1, 77.9)]):
        conn.execute(
            """
            INSERT INTO observations (id, patient_id, loinc_code, display, value, unit, interpretation, effective_at,
                                      category, source)
            VALUES (%s, %s, %s, %s, %s, %s, 'N', %s, 'vital-signs', 'manual') ON CONFLICT DO NOTHING
            """,
            (WEIGHT_OBS[i], P_MAYA, w.loinc, w.display, kg, w.unit, ctx.at(ctx.days(-days_ago), 7, 10)),
        )
    answers = {"sick": False, "control": False, "one_stone": False, "fat": False, "food": False}
    conn.execute(
        """
        INSERT INTO weight_screenings (id, patient_id, answers, score, positive, created_at)
        VALUES (%s, %s, %s, 0, false, %s) ON CONFLICT DO NOTHING
        """,
        (SCREENING, P_MAYA, Jsonb(answers), ctx.at(ctx.days(-22), 7, 50)),
    )
    conn.execute(
        """
        INSERT INTO weight_goals (id, patient_id, start_weight_kg, target_weight_kg, pace_kg_week, height_cm,
                                  screening_id, created_at)
        VALUES (%s, %s, 79.2, 72, 0.5, 165, %s, %s) ON CONFLICT DO NOTHING
        """,
        (GOAL, P_MAYA, SCREENING, ctx.at(ctx.days(-22), 8)),
    )


def _mind(conn, ctx: SeedContext) -> None:
    results = [
        (_id(13030), _id(13034), "phq9", [1, 1, 1, 1, 1, 1, 0, 0, 0], 30, "Somewhat difficult"),
        (_id(13031), _id(13035), "gad7", [1, 1, 1, 1, 0, 1, 1], 30, "Somewhat difficult"),
        (_id(13032), _id(13036), "phq9", [1, 1, 1, 1, 0, 1, 0, 0, 0], 2, "Somewhat difficult"),
        (_id(13033), _id(13037), "gad7", [1, 1, 1, 1, 0, 1, 0], 2, "Not difficult at all"),
    ]
    for rid, oid, inst, items, days_ago, difficulty in results:
        spec, s = INSTRUMENTS[inst], score(inst, items)
        at = ctx.at(ctx.days(-days_ago), 20, 15 if inst == "phq9" else 20)
        conn.execute(
            """
            INSERT INTO observations (id, patient_id, loinc_code, display, value, unit, interpretation, effective_at,
                                      category, source, note)
            VALUES (%s, %s, %s, %s, %s, '{score}', 'N', %s, 'survey', 'manual', %s) ON CONFLICT DO NOTHING
            """,
            (oid, P_MAYA, spec["loinc"], spec["display"], s["total"], at, f"{spec['title']} · {s['severity_label']}"),
        )
        conn.execute(
            """
            INSERT INTO mind_questionnaire_responses (id, patient_id, instrument, items, difficulty, total, severity,
                                                      item9, crisis, observation_id, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, false, %s, %s) ON CONFLICT DO NOTHING
            """,
            (rid, P_MAYA, inst, items, difficulty, s["total"], s["severity"], s["item9"], oid, at),
        )
    conn.execute(
        "INSERT INTO mind_preferences (patient_id, retest_reminders, retest_weeks) VALUES (%s, true, 4) ON CONFLICT DO NOTHING",
        (P_MAYA,),
    )
    entries = [
        (6, 3, ["work", "stress"], "Long day, deadline moved up.", False),
        (4, 4, ["exercise", "outdoors"], "Walked by the river at lunch.", False),
        (3, 3, ["sleep"], None, False),
        (1, 4, ["family", "rest"], "Dinner with David and Mom. Felt good.", True),
    ]
    for i, (days_ago, mood, tags, note, shared) in enumerate(entries):
        conn.execute(
            """
            INSERT INTO mind_journal_entries (id, patient_id, mood, tags, note, shared, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
            """,
            (_id(13200 + i), P_MAYA, mood, tags, note, shared, ctx.at(ctx.days(-days_ago), 21, 5)),
        )


def _challenges(conn, ctx: SeedContext) -> None:
    # A completed hydration challenge five weeks ago, with its points and badges.
    start = ctx.days(-40)
    new = conn.execute(
        """
        INSERT INTO challenge_enrollments (id, patient_id, definition_id, started_on, ends_on, status, periods_met,
                                           current_streak, best_streak, completed_at, created_at)
        VALUES (%s, %s, 'hydration_8_7d', %s, %s, 'completed', 7, 7, 7, %s, %s) ON CONFLICT DO NOTHING RETURNING id
        """,
        (HYDRATION_ENROLLMENT, P_MAYA, start, start + timedelta(days=6), ctx.at(start + timedelta(days=6), 21),
         ctx.at(start, 8)),
    ).fetchone()
    if new:
        for i in range(7):
            day = start + timedelta(days=i)
            conn.execute(
                """
                INSERT INTO challenge_points (patient_id, delta, reason, enrollment_id, dedupe_key, created_at)
                VALUES (%s, 10, '8 glasses of water a day for 7 days: target met', %s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (P_MAYA, HYDRATION_ENROLLMENT, f"enr:{HYDRATION_ENROLLMENT}:{day:%Y-%m-%d}", ctx.at(day, 22)),
            )
        done = ctx.at(start + timedelta(days=6), 22)
        conn.execute(
            """
            INSERT INTO challenge_points (patient_id, delta, reason, enrollment_id, dedupe_key, created_at)
            VALUES (%s, 100, 'Completed: 8 glasses of water a day for 7 days', %s, %s, %s) ON CONFLICT DO NOTHING
            """,
            (P_MAYA, HYDRATION_ENROLLMENT, f"enr:{HYDRATION_ENROLLMENT}:complete", done),
        )
        for i, badge in enumerate(["first_goal_day", "streak_3", "streak_7", "complete_hydration_8_7d"]):
            conn.execute(
                """
                INSERT INTO challenge_badges (patient_id, badge, title, enrollment_id, awarded_at)
                VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (P_MAYA, badge, BADGES[badge], HYDRATION_ENROLLMENT, ctx.at(start + timedelta(days=min(6, i * 2)), 22)),
            )

    # One redeemed demo perk.
    new = conn.execute(
        """
        INSERT INTO challenge_redemptions (id, patient_id, reward_id, points, code, created_at)
        VALUES (%s, %s, 'demo-smoothie', 100, 'DEMO-7K2Q-1B9F', %s) ON CONFLICT DO NOTHING RETURNING id
        """,
        (REDEMPTION, P_MAYA, ctx.at(ctx.days(-20), 13)),
    ).fetchone()
    if new:
        conn.execute(
            """
            INSERT INTO challenge_points (patient_id, delta, reason, dedupe_key, created_at)
            VALUES (%s, -100, 'Redeemed: Smoothie at the fictional Harbor Leaf Cafe', %s, %s) ON CONFLICT DO NOTHING
            """,
            (P_MAYA, f"redeem:{REDEMPTION}", ctx.at(ctx.days(-20), 13)),
        )

    # The active steps challenge: five days met in a row so far, today still open.
    start = ctx.days(-5)
    new = conn.execute(
        """
        INSERT INTO challenge_enrollments (id, patient_id, definition_id, started_on, ends_on, created_at)
        VALUES (%s, %s, 'steps_7k_7d', %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id
        """,
        (STEPS_ENROLLMENT, P_MAYA, start, start + timedelta(days=6), ctx.at(start, 7, 30)),
    ).fetchone()
    if new:
        steps = CODES["steps"]
        for i, n in enumerate([8200, 7400, 9100, 7600, 8800]):
            conn.execute(
                """
                INSERT INTO observations (id, patient_id, loinc_code, display, value, unit, interpretation, effective_at,
                                          category, source, device)
                VALUES (%s, %s, %s, %s, %s, %s, 'N', %s, 'activity', 'device', 'Demo step counter') ON CONFLICT DO NOTHING
                """,
                (_id(13050 + i), P_MAYA, steps.loinc, steps.display, n, steps.unit, ctx.at(start + timedelta(days=i), 21)),
            )
        # Points, badges and milestones exactly as the daily job would award them (same dedupe keys).
        previous = conn.row_factory
        conn.row_factory = dict_row
        try:
            sync_enrollment(conn, STEPS_ENROLLMENT, ctx.today)
        finally:
            conn.row_factory = previous
