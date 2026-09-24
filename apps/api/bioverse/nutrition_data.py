"""Reference data for nutrition: the food list, default daily targets and the tip library.

Food values are per serving, rounded from public USDA FoodData Central (SR Legacy / FNDDS) entries for a
typical product. Brands and recipes vary; the app says so. `veg` counts vegetable servings, where one
serving is half a MyPlate cup-equivalent (1/2 cup cooked or chopped, 1 cup raw leafy greens). `water`
is millilitres of plain drinks that count toward hydration (water, sparkling water, unsweetened tea,
black coffee).

Targets and tips are general education with a named source, never personalized medical advice. A
clinician can override any target for a patient (routers/nutrition.py).
"""

from __future__ import annotations

from dataclasses import dataclass

# id, name, category, serving, grams, kcal, protein, carbs, fat, fiber, sugar, sodium_mg, veg, water_ml, aliases
_F = [
    # --- Grains and breakfast ---
    ("oatmeal-cooked", "Oatmeal, cooked with water", "Grains", "1 cup", 234, 166, 5.9, 28, 3.6, 4, 0.6, 9, 0, 0, ["oats", "porridge"]),
    ("oatmeal-instant-flavored", "Instant oatmeal, maple and brown sugar", "Grains", "1 packet, prepared", 198, 157, 4, 32, 2, 3, 12, 250, 0, 0, ["instant oats"]),
    ("granola", "Granola", "Grains", "1/2 cup", 50, 220, 5, 32, 8, 3, 12, 85, 0, 0, ["muesli"]),
    ("corn-flakes", "Corn flakes cereal", "Grains", "1 cup", 28, 100, 2, 24, 0.2, 0.9, 2.4, 200, 0, 0, ["cereal", "cornflakes"]),
    ("bran-flakes", "Bran flakes cereal", "Grains", "3/4 cup", 29, 96, 3, 24, 0.6, 5.5, 5, 220, 0, 0, ["bran cereal"]),
    ("toasted-oat-cereal", "Toasted oat cereal (O-shaped)", "Grains", "1 cup", 28, 104, 3.5, 20, 1.8, 2.8, 1.2, 140, 0, 0, ["oat cereal", "cheerios"]),
    ("white-bread", "White bread", "Grains", "1 slice", 28, 75, 2.6, 14, 1, 0.7, 1.5, 135, 0, 0, ["bread", "toast"]),
    ("whole-wheat-bread", "Whole-wheat bread", "Grains", "1 slice", 32, 80, 4, 14, 1.1, 1.9, 1.4, 146, 0, 0, ["wholemeal bread", "brown bread", "wheat toast"]),
    ("bagel-plain", "Bagel, plain", "Grains", "1 medium", 105, 270, 10.5, 53, 1.7, 2.3, 5, 430, 0, 0, ["bagel"]),
    ("english-muffin", "English muffin", "Grains", "1 muffin", 57, 134, 4.4, 26, 1, 1.5, 2, 240, 0, 0, []),
    ("croissant", "Croissant, butter", "Grains", "1 medium", 57, 231, 4.7, 26, 12, 1.5, 6.4, 310, 0, 0, ["pastry"]),
    ("pancakes", "Pancakes, plain", "Grains", "2 medium (4 inch)", 76, 175, 4.8, 22, 7.4, 0.8, 4, 330, 0, 0, ["hotcakes"]),
    ("waffle-frozen", "Waffle, frozen, toasted", "Grains", "1 waffle", 35, 95, 2.3, 15, 3, 0.8, 1.7, 220, 0, 0, ["waffle"]),
    ("white-rice", "White rice, cooked", "Grains", "1 cup", 158, 205, 4.3, 45, 0.4, 0.6, 0.1, 2, 0, 0, ["rice", "steamed rice"]),
    ("brown-rice", "Brown rice, cooked", "Grains", "1 cup", 195, 218, 4.5, 46, 1.6, 3.5, 0.7, 10, 0, 0, []),
    ("pasta-cooked", "Pasta, cooked, plain", "Grains", "1 cup", 140, 221, 8, 43, 1.3, 2.5, 0.8, 1, 0, 0, ["spaghetti", "noodles", "penne", "macaroni"]),
    ("quinoa", "Quinoa, cooked", "Grains", "1 cup", 185, 222, 8.1, 39, 3.6, 5.2, 1.6, 13, 0, 0, []),
    ("couscous", "Couscous, cooked", "Grains", "1 cup", 157, 176, 6, 36, 0.3, 2.2, 0.2, 8, 0, 0, []),
    ("tortilla-flour", "Flour tortilla", "Grains", "1 medium (8 inch)", 49, 146, 3.9, 24, 3.7, 1.7, 1, 330, 0, 0, ["wrap", "tortilla"]),
    ("tortilla-corn", "Corn tortilla", "Grains", "1 small (6 inch)", 26, 57, 1.5, 12, 0.7, 1.6, 0.2, 11, 0, 0, []),
    ("dinner-roll", "Dinner roll", "Grains", "1 roll", 28, 84, 2.7, 14, 2, 0.8, 1.5, 146, 0, 0, ["bread roll", "bun"]),
    ("saltine-crackers", "Saltine crackers", "Grains", "5 crackers", 15, 63, 1.4, 11, 1.3, 0.4, 0.2, 160, 0, 0, ["crackers"]),
    ("pita-whole-wheat", "Whole-wheat pita", "Grains", "1 pita (6.5 inch)", 64, 170, 6.3, 35, 1.7, 4.7, 0.5, 340, 0, 0, ["pita"]),
    ("cornbread", "Cornbread", "Grains", "1 piece", 60, 188, 4.3, 29, 6, 1.4, 7, 330, 0, 0, []),
    # --- Protein foods ---
    ("egg-boiled", "Egg, hard-boiled", "Protein", "1 large", 50, 78, 6.3, 0.6, 5.3, 0, 0.6, 62, 0, 0, ["egg", "boiled egg"]),
    ("eggs-scrambled", "Eggs, scrambled", "Protein", "2 large eggs", 122, 182, 12, 2.4, 13.4, 0, 1.6, 176, 0, 0, ["scrambled eggs", "eggs"]),
    ("egg-whites", "Egg whites, cooked", "Protein", "3 egg whites", 99, 51, 10.8, 0.7, 0.2, 0, 0.7, 164, 0, 0, []),
    ("chicken-breast", "Chicken breast, grilled, skinless", "Protein", "3 oz (85 g)", 85, 140, 26, 0, 3, 0, 0, 64, 0, 0, ["chicken", "grilled chicken"]),
    ("chicken-thigh", "Chicken thigh, roasted, with skin", "Protein", "3 oz (85 g)", 85, 197, 21, 0, 12, 0, 0, 75, 0, 0, []),
    ("rotisserie-chicken", "Rotisserie chicken, with skin", "Protein", "3 oz (85 g)", 85, 190, 23, 0, 10, 0, 0, 330, 0, 0, ["roast chicken"]),
    ("fried-chicken", "Fried chicken breast, breaded", "Protein", "1 piece", 140, 364, 35, 12, 19, 0.4, 0, 880, 0, 0, []),
    ("chicken-nuggets", "Chicken nuggets", "Protein", "6 pieces", 96, 270, 14, 16, 17, 1, 0, 510, 0, 0, ["nuggets"]),
    ("deli-turkey", "Deli turkey slices", "Protein", "2 oz (56 g)", 56, 60, 10, 2, 1, 0, 1, 560, 0, 0, ["turkey"]),
    ("deli-ham", "Deli ham slices", "Protein", "2 oz (56 g)", 56, 61, 9.4, 1.5, 2, 0, 0, 690, 0, 0, ["ham"]),
    ("bacon", "Bacon, cooked", "Protein", "2 slices", 16, 86, 5.9, 0.2, 6.7, 0, 0, 300, 0, 0, []),
    ("breakfast-sausage", "Pork breakfast sausage", "Protein", "2 links", 48, 170, 9, 0.5, 15, 0, 0.5, 420, 0, 0, ["sausage"]),
    ("beef-patty", "Ground beef patty, 85% lean, broiled", "Protein", "3 oz (85 g)", 85, 213, 22, 0, 13, 0, 0, 72, 0, 0, ["beef", "burger patty"]),
    ("sirloin-steak", "Sirloin steak, lean, broiled", "Protein", "3 oz (85 g)", 85, 160, 26, 0, 6, 0, 0, 54, 0, 0, ["steak"]),
    ("pork-chop", "Pork chop, broiled", "Protein", "3 oz (85 g)", 85, 172, 26, 0, 7, 0, 0, 52, 0, 0, ["pork"]),
    ("salmon-baked", "Salmon, baked", "Protein", "3 oz (85 g)", 85, 175, 19, 0, 10.5, 0, 0, 52, 0, 0, ["salmon", "fish"]),
    ("tuna-canned", "Tuna, canned in water, drained", "Protein", "3 oz (85 g)", 85, 73, 16.5, 0, 0.7, 0, 0, 210, 0, 0, ["tuna"]),
    ("shrimp-cooked", "Shrimp, cooked", "Protein", "3 oz (85 g)", 85, 84, 20, 0.2, 0.2, 0, 0, 190, 0, 0, ["prawns", "shrimp"]),
    ("cod-baked", "Cod, baked", "Protein", "3 oz (85 g)", 85, 89, 19, 0, 0.7, 0, 0, 66, 0, 0, ["white fish"]),
    ("tilapia-baked", "Tilapia, baked", "Protein", "3 oz (85 g)", 85, 109, 22, 0, 2.3, 0, 0, 48, 0, 0, []),
    ("tofu-firm", "Tofu, firm", "Protein", "1/2 cup", 126, 181, 21.8, 3.5, 11, 2.9, 0.8, 18, 0, 0, ["tofu", "bean curd"]),
    ("black-beans", "Black beans, cooked from dry", "Protein", "1/2 cup", 86, 114, 7.6, 20, 0.5, 7.5, 0.3, 1, 1, 0, ["beans"]),
    ("black-beans-canned", "Black beans, canned", "Protein", "1/2 cup", 120, 109, 7, 20, 0.4, 8, 0.3, 460, 1, 0, []),
    ("chickpeas-canned", "Chickpeas, canned, drained", "Protein", "1/2 cup", 120, 139, 7.2, 22, 2.3, 6.4, 0, 290, 1, 0, ["garbanzo beans", "chickpeas"]),
    ("lentils", "Lentils, cooked", "Protein", "1/2 cup", 99, 115, 8.9, 20, 0.4, 7.8, 1.8, 2, 1, 0, ["dal"]),
    ("hummus", "Hummus", "Protein", "2 tbsp", 30, 70, 2, 4, 5, 1.2, 0, 130, 0, 0, []),
    ("peanut-butter", "Peanut butter", "Protein", "2 tbsp", 32, 190, 7, 7, 16, 1.9, 3, 140, 0, 0, []),
    ("almonds", "Almonds", "Protein", "1 oz (about 23)", 28, 164, 6, 6, 14, 3.5, 1.2, 0, 0, 0, ["nuts"]),
    ("walnuts", "Walnuts", "Protein", "1 oz", 28, 185, 4.3, 3.9, 18.5, 1.9, 0.7, 1, 0, 0, []),
    ("mixed-nuts-salted", "Mixed nuts, salted", "Protein", "1 oz", 28, 172, 5, 7, 15, 2, 1.2, 120, 0, 0, ["salted nuts"]),
    # --- Dairy and alternatives ---
    ("greek-yogurt", "Greek yogurt, plain, nonfat", "Dairy", "1 container (170 g)", 170, 100, 17, 6, 0.7, 0, 6, 61, 0, 0, ["yogurt", "yoghurt"]),
    ("fruit-yogurt", "Fruit yogurt, low-fat", "Dairy", "1 container (170 g)", 170, 170, 7, 32, 2, 0, 26, 100, 0, 0, ["flavored yogurt"]),
    ("cottage-cheese", "Cottage cheese, 2%", "Dairy", "1/2 cup", 113, 92, 12, 5, 2.6, 0, 4.6, 350, 0, 0, []),
    ("cheddar", "Cheddar cheese", "Dairy", "1 oz (28 g)", 28, 114, 7, 0.4, 9.4, 0, 0.1, 180, 0, 0, ["cheese"]),
    ("mozzarella", "Mozzarella, part-skim", "Dairy", "1 oz (28 g)", 28, 72, 6.9, 0.8, 4.5, 0, 0.3, 175, 0, 0, []),
    ("american-cheese", "American cheese slice", "Dairy", "1 slice", 21, 65, 3.5, 1.5, 5, 0, 1, 270, 0, 0, ["cheese slice"]),
    ("feta", "Feta cheese", "Dairy", "1 oz (28 g)", 28, 75, 4, 1.2, 6, 0, 0.1, 320, 0, 0, []),
    ("string-cheese", "String cheese", "Dairy", "1 stick", 28, 80, 7, 1, 6, 0, 0, 200, 0, 0, []),
    ("cream-cheese", "Cream cheese", "Dairy", "2 tbsp", 29, 99, 1.8, 1.6, 9.8, 0, 0.9, 90, 0, 0, []),
    ("milk-2", "Milk, 2%", "Dairy", "1 cup", 244, 122, 8, 12, 4.8, 0, 12, 115, 0, 0, ["milk"]),
    ("milk-skim", "Milk, skim", "Dairy", "1 cup", 245, 83, 8.3, 12, 0.2, 0, 12, 103, 0, 0, ["nonfat milk"]),
    ("soy-milk", "Soy milk, unsweetened", "Dairy", "1 cup", 243, 80, 7, 4, 4, 1, 1, 85, 0, 0, []),
    ("almond-milk", "Almond milk, unsweetened", "Dairy", "1 cup", 240, 39, 1.5, 3.4, 2.5, 0.5, 0, 170, 0, 0, []),
    ("ice-cream", "Vanilla ice cream", "Dairy", "1/2 cup", 66, 137, 2.3, 15.6, 7.3, 0.5, 14, 53, 0, 0, []),
    # --- Vegetables ---
    ("broccoli-cooked", "Broccoli, steamed", "Vegetables", "1/2 cup", 78, 27, 1.9, 5.6, 0.3, 2.6, 1.1, 32, 1, 0, ["broccoli"]),
    ("broccoli-raw", "Broccoli, raw", "Vegetables", "1 cup chopped", 91, 31, 2.5, 6, 0.3, 2.4, 1.5, 30, 2, 0, []),
    ("spinach-raw", "Spinach, raw", "Vegetables", "1 cup", 30, 7, 0.9, 1.1, 0.1, 0.7, 0.1, 24, 1, 0, ["spinach"]),
    ("spinach-cooked", "Spinach, cooked", "Vegetables", "1/2 cup", 90, 21, 2.7, 3.4, 0.2, 2.2, 0.4, 63, 1, 0, []),
    ("mixed-greens", "Mixed salad greens", "Vegetables", "2 cups", 72, 12, 1, 2.4, 0.2, 1.5, 0.9, 20, 2, 0, ["salad", "lettuce", "greens"]),
    ("side-salad-ranch", "Side salad with ranch dressing", "Vegetables", "1 bowl", 150, 150, 1.5, 6, 13.5, 1.8, 3, 300, 1, 0, ["side salad"]),
    ("kale-cooked", "Kale, cooked", "Vegetables", "1/2 cup", 65, 18, 1.2, 3.6, 0.3, 1.3, 0.8, 15, 1, 0, ["kale"]),
    ("baby-carrots", "Baby carrots", "Vegetables", "10 carrots", 100, 35, 0.6, 8.2, 0.1, 2.9, 4.8, 78, 1, 0, ["carrots", "carrot sticks"]),
    ("carrots-cooked", "Carrots, cooked", "Vegetables", "1/2 cup", 78, 27, 0.6, 6.4, 0.1, 2.3, 2.7, 45, 1, 0, []),
    ("green-beans", "Green beans, cooked", "Vegetables", "1/2 cup", 62, 22, 1.2, 4.9, 0.2, 2, 1, 1, 1, 0, ["string beans"]),
    ("peas", "Green peas, cooked", "Vegetables", "1/2 cup", 80, 67, 4.3, 12.5, 0.2, 4.4, 4.7, 2, 1, 0, []),
    ("corn", "Sweet corn, cooked", "Vegetables", "1/2 cup", 82, 79, 2.8, 17, 1.1, 2, 3.9, 1, 1, 0, ["corn on the cob"]),
    ("tomato", "Tomato, raw", "Vegetables", "1 medium", 123, 22, 1.1, 4.8, 0.2, 1.5, 3.2, 6, 1, 0, ["tomatoes"]),
    ("cucumber", "Cucumber, sliced", "Vegetables", "1/2 cup", 52, 8, 0.3, 1.9, 0.1, 0.3, 0.9, 1, 1, 0, []),
    ("bell-pepper", "Bell pepper, raw", "Vegetables", "1 medium", 119, 31, 1.2, 7.2, 0.4, 2.5, 5, 5, 2, 0, ["pepper", "capsicum"]),
    ("zucchini", "Zucchini, cooked", "Vegetables", "1/2 cup", 90, 15, 1.1, 2.7, 0.3, 0.9, 1.7, 3, 1, 0, ["courgette"]),
    ("cauliflower", "Cauliflower, cooked", "Vegetables", "1/2 cup", 62, 14, 1.1, 2.5, 0.3, 1.4, 1.3, 9, 1, 0, []),
    ("brussels-sprouts", "Brussels sprouts, cooked", "Vegetables", "1/2 cup", 78, 28, 2, 5.5, 0.4, 2, 1.4, 16, 1, 0, []),
    ("mushrooms", "Mushrooms, raw, sliced", "Vegetables", "1/2 cup", 35, 8, 1.1, 1.1, 0.1, 0.4, 0.7, 2, 1, 0, []),
    ("onion", "Onion, chopped", "Vegetables", "1/2 cup", 80, 32, 0.9, 7.5, 0.1, 1.4, 3.4, 3, 1, 0, []),
    ("sweet-potato", "Sweet potato, baked", "Vegetables", "1 medium", 114, 103, 2.3, 24, 0.2, 3.8, 7.4, 41, 1.5, 0, ["yam"]),
    ("baked-potato", "Potato, baked, with skin", "Vegetables", "1 medium", 173, 161, 4.3, 37, 0.2, 3.8, 2, 17, 2, 0, ["potato", "jacket potato"]),
    ("mashed-potatoes", "Mashed potatoes with milk and butter", "Vegetables", "1 cup", 210, 237, 4, 35, 9, 3.2, 3, 630, 2, 0, []),
    ("french-fries", "French fries", "Vegetables", "1 medium serving", 117, 365, 4, 48, 17, 4.4, 0.3, 250, 0, 0, ["fries", "chips"]),
    ("edamame", "Edamame, shelled", "Vegetables", "1/2 cup", 78, 94, 9.2, 6.9, 4, 4, 1.7, 5, 1, 0, ["soybeans"]),
    ("avocado", "Avocado", "Vegetables", "1/2 avocado", 100, 160, 2, 8.5, 14.7, 6.7, 0.7, 7, 1, 0, ["guacamole"]),
    ("coleslaw", "Coleslaw, creamy", "Vegetables", "1/2 cup", 60, 88, 0.8, 7.5, 6, 1.1, 6, 160, 1, 0, ["slaw"]),
    ("vegetable-soup-canned", "Vegetable soup, canned", "Vegetables", "1 cup", 241, 90, 3, 16, 1.5, 3, 5, 720, 1, 0, ["veggie soup"]),
    ("stir-fried-vegetables", "Stir-fried vegetables with soy sauce", "Vegetables", "1 cup", 150, 90, 3, 10, 4.5, 3, 4, 520, 2, 0, ["stir fry vegetables"]),
    ("salsa", "Salsa", "Condiments", "2 tbsp", 32, 10, 0.5, 2, 0, 0.5, 1.3, 200, 0, 0, []),
    ("dill-pickle", "Dill pickle", "Condiments", "1 spear", 35, 4, 0.2, 0.8, 0.1, 0.3, 0.4, 280, 0, 0, ["pickle"]),
    # --- Fruit ---
    ("apple", "Apple", "Fruit", "1 medium", 182, 95, 0.5, 25, 0.3, 4.4, 19, 2, 0, 0, []),
    ("banana", "Banana", "Fruit", "1 medium", 118, 105, 1.3, 27, 0.4, 3.1, 14.4, 1, 0, 0, []),
    ("orange", "Orange", "Fruit", "1 medium", 131, 62, 1.2, 15.4, 0.2, 3.1, 12.2, 0, 0, 0, []),
    ("strawberries", "Strawberries", "Fruit", "1 cup halves", 152, 49, 1, 11.7, 0.5, 3, 7.4, 2, 0, 0, ["berries"]),
    ("blueberries", "Blueberries", "Fruit", "1 cup", 148, 84, 1.1, 21.4, 0.5, 3.6, 14.7, 1, 0, 0, []),
    ("grapes", "Grapes", "Fruit", "1 cup", 151, 104, 1.1, 27.3, 0.2, 1.4, 23.4, 3, 0, 0, []),
    ("watermelon", "Watermelon", "Fruit", "1 cup diced", 152, 46, 0.9, 11.5, 0.2, 0.6, 9.4, 2, 0, 0, ["melon"]),
    ("pear", "Pear", "Fruit", "1 medium", 178, 101, 0.6, 27, 0.2, 5.5, 17, 2, 0, 0, []),
    ("peach", "Peach", "Fruit", "1 medium", 150, 59, 1.4, 14.3, 0.4, 2.3, 12.6, 0, 0, 0, []),
    ("mango", "Mango", "Fruit", "1 cup pieces", 165, 99, 1.4, 24.7, 0.6, 2.6, 22.5, 2, 0, 0, []),
    ("pineapple", "Pineapple", "Fruit", "1 cup chunks", 165, 82, 0.9, 21.6, 0.2, 2.3, 16.3, 2, 0, 0, []),
    ("raisins", "Raisins", "Fruit", "1 small box", 43, 129, 1.3, 34, 0.2, 1.6, 25, 11, 0, 0, []),
    # --- Mixed dishes and takeout ---
    ("cheese-pizza", "Cheese pizza", "Mixed dishes", "1 slice (14 inch pie)", 107, 285, 12, 36, 10, 2.5, 3.8, 640, 0, 0, ["pizza"]),
    ("pepperoni-pizza", "Pepperoni pizza", "Mixed dishes", "1 slice (14 inch pie)", 111, 313, 13, 35, 13, 2.5, 3.8, 760, 0, 0, []),
    ("hamburger", "Hamburger, single patty, with bun", "Mixed dishes", "1 burger", 110, 250, 12.5, 31, 9, 1.2, 6, 500, 0, 0, ["burger"]),
    ("cheeseburger", "Cheeseburger, single patty, with bun", "Mixed dishes", "1 burger", 119, 300, 15, 33, 12, 1.5, 7, 740, 0, 0, []),
    ("hot-dog", "Hot dog with bun", "Mixed dishes", "1 hot dog", 98, 280, 10, 23, 16, 0.8, 4, 780, 0, 0, []),
    ("turkey-sandwich", "Turkey and cheese sandwich on wheat", "Mixed dishes", "1 sandwich", 200, 360, 26, 34, 13, 4, 5, 1250, 0, 0, ["sandwich", "deli sandwich"]),
    ("ham-cheese-sandwich", "Ham and cheese sandwich", "Mixed dishes", "1 sandwich", 180, 350, 21, 33, 15, 2, 5, 1350, 0, 0, []),
    ("blt-sandwich", "BLT sandwich", "Mixed dishes", "1 sandwich", 160, 400, 13, 30, 25, 2, 4, 850, 0, 0, ["blt"]),
    ("grilled-cheese", "Grilled cheese sandwich", "Mixed dishes", "1 sandwich", 120, 390, 14, 30, 24, 1.5, 4, 850, 0, 0, []),
    ("pbj-sandwich", "Peanut butter and jelly sandwich", "Mixed dishes", "1 sandwich", 93, 345, 11, 44, 15, 2.7, 17, 430, 0, 0, ["pb&j"]),
    ("chicken-caesar-salad", "Chicken Caesar salad with dressing", "Mixed dishes", "1 bowl", 300, 440, 33, 13, 28, 3, 3, 1080, 2, 0, ["caesar salad"]),
    ("chicken-garden-salad", "Grilled chicken garden salad, light vinaigrette", "Mixed dishes", "1 bowl", 350, 290, 30, 14, 13, 4.5, 7, 650, 3, 0, ["chicken salad"]),
    ("chicken-noodle-soup", "Chicken noodle soup, canned", "Mixed dishes", "1 cup", 241, 90, 6, 10, 2.5, 1, 1, 850, 0, 0, ["soup"]),
    ("tomato-soup", "Tomato soup, canned, made with water", "Mixed dishes", "1 cup", 244, 90, 2, 20, 0.7, 1.5, 12, 690, 1, 0, []),
    ("instant-ramen", "Instant ramen noodles with seasoning", "Mixed dishes", "1 package", 85, 380, 8, 52, 14, 2, 1.5, 1600, 0, 0, ["ramen", "instant noodles"]),
    ("chili-with-beans", "Chili con carne with beans, canned", "Mixed dishes", "1 cup", 256, 270, 17, 25, 12, 7, 3, 1030, 1, 0, ["chili"]),
    ("spaghetti-meat-sauce", "Spaghetti with meat sauce", "Mixed dishes", "1 1/2 cups", 370, 450, 22, 60, 14, 6, 11, 980, 1, 0, ["spaghetti bolognese"]),
    ("mac-and-cheese", "Macaroni and cheese, boxed", "Mixed dishes", "1 cup", 200, 350, 10, 48, 13, 2, 6, 720, 0, 0, ["mac n cheese"]),
    ("lasagna-frozen", "Lasagna with meat, frozen meal", "Mixed dishes", "1 tray", 284, 360, 20, 38, 13, 3, 8, 960, 1, 0, ["lasagna"]),
    ("bean-burrito", "Bean and cheese burrito", "Mixed dishes", "1 large", 200, 440, 16, 60, 14, 9, 3, 1100, 1, 0, ["burrito"]),
    ("chicken-burrito-bowl", "Chicken burrito bowl with rice, beans, salsa and cheese", "Mixed dishes", "1 bowl", 450, 650, 43, 72, 19, 13, 5, 1700, 2, 0, ["burrito bowl"]),
    ("beef-tacos", "Beef tacos, hard shell", "Mixed dishes", "2 tacos", 170, 340, 16, 26, 20, 5, 2, 610, 0.5, 0, ["tacos"]),
    ("chicken-fried-rice", "Chicken fried rice", "Mixed dishes", "1 1/2 cups", 250, 430, 17, 58, 14, 2, 2, 1000, 0.5, 0, ["fried rice"]),
    ("california-roll", "California roll", "Mixed dishes", "6 pieces", 185, 255, 9, 38, 7, 3.5, 7, 430, 0, 0, ["sushi"]),
    ("chicken-stir-fry-rice", "Chicken and vegetable stir-fry with rice", "Mixed dishes", "1 plate", 400, 520, 32, 64, 14, 5, 9, 1300, 2, 0, ["stir fry"]),
    ("beef-stew", "Beef stew with vegetables", "Mixed dishes", "1 cup", 245, 220, 16, 16, 10, 3, 3, 700, 1, 0, ["stew"]),
    ("meatloaf", "Meatloaf", "Mixed dishes", "1 slice", 115, 250, 17, 9, 15, 0.5, 4, 560, 0, 0, []),
    ("rice-and-beans", "Rice and beans", "Mixed dishes", "1 cup", 240, 280, 9, 52, 3.5, 7, 1, 540, 1, 0, []),
    ("veggie-omelet", "Vegetable omelet with cheese", "Mixed dishes", "2-egg omelet", 170, 260, 17, 5, 19, 1, 3, 430, 1, 0, ["omelet", "omelette"]),
    ("breakfast-sandwich", "Egg, cheese and sausage breakfast sandwich", "Mixed dishes", "1 sandwich", 165, 450, 20, 30, 27, 2, 3, 1000, 0, 0, ["breakfast muffin"]),
    ("avocado-toast", "Avocado toast on whole-grain bread", "Mixed dishes", "1 slice", 130, 240, 6, 22, 15, 8.5, 2, 300, 1, 0, []),
    # --- Snacks and sweets ---
    ("potato-chips", "Potato chips", "Snacks", "1 oz (about 15 chips)", 28, 152, 2, 15, 10, 1.2, 0.1, 150, 0, 0, ["crisps", "chips"]),
    ("pretzels", "Pretzels, salted", "Snacks", "1 oz", 28, 108, 2.9, 22.7, 0.8, 0.9, 0.8, 385, 0, 0, []),
    ("popcorn-air", "Popcorn, air-popped", "Snacks", "3 cups", 24, 93, 3, 18.6, 1.1, 3.6, 0.2, 2, 0, 0, ["popcorn"]),
    ("popcorn-butter", "Microwave popcorn, butter", "Snacks", "3 cups popped", 33, 170, 2.5, 17, 11, 3, 0.3, 290, 0, 0, []),
    ("granola-bar", "Granola bar, chewy", "Snacks", "1 bar", 24, 100, 1.5, 17, 3, 1, 7, 70, 0, 0, []),
    ("protein-bar", "Protein bar", "Snacks", "1 bar", 60, 220, 20, 23, 7, 3, 6, 200, 0, 0, []),
    ("trail-mix", "Trail mix", "Snacks", "1/4 cup", 38, 175, 5, 17, 11, 2, 11, 85, 0, 0, []),
    ("dark-chocolate", "Dark chocolate, 70-85%", "Snacks", "1 oz", 28, 170, 2.2, 13, 12, 3.1, 6.8, 6, 0, 0, ["chocolate"]),
    ("chocolate-chip-cookies", "Chocolate chip cookies", "Snacks", "2 small cookies", 30, 140, 1.6, 19, 7, 0.7, 11, 100, 0, 0, ["cookies", "biscuits"]),
    ("glazed-donut", "Glazed donut", "Snacks", "1 medium", 64, 269, 4, 31, 15, 0.8, 13, 210, 0, 0, ["doughnut"]),
    ("blueberry-muffin", "Blueberry muffin", "Snacks", "1 medium", 113, 420, 6, 58, 19, 1.5, 32, 410, 0, 0, ["muffin"]),
    # --- Drinks ---
    ("water-glass", "Water", "Drinks", "1 glass (8 fl oz, 237 ml)", 237, 0, 0, 0, 0, 0, 0, 5, 0, 237, ["water", "glass of water"]),
    ("water-bottle", "Water, bottle", "Drinks", "1 bottle (500 ml)", 500, 0, 0, 0, 0, 0, 0, 10, 0, 500, ["bottle of water"]),
    ("sparkling-water", "Sparkling water, unsweetened", "Drinks", "1 can (355 ml)", 355, 0, 0, 0, 0, 0, 0, 10, 0, 355, ["seltzer", "soda water"]),
    ("coffee-black", "Coffee, brewed, black", "Drinks", "1 cup (8 fl oz)", 237, 2, 0.3, 0, 0, 0, 0, 5, 0, 237, ["coffee"]),
    ("tea-unsweetened", "Tea, brewed, unsweetened", "Drinks", "1 cup (8 fl oz)", 237, 2, 0, 0.7, 0, 0, 0, 7, 0, 237, ["tea"]),
    ("latte", "Latte with 2% milk", "Drinks", "16 fl oz", 450, 190, 13, 19, 7, 0, 17, 170, 0, 0, ["cappuccino"]),
    ("sweet-tea", "Sweet tea", "Drinks", "16 fl oz", 480, 180, 0, 45, 0, 0, 44, 20, 0, 0, ["iced tea"]),
    ("cola", "Cola", "Drinks", "1 can (12 fl oz)", 368, 140, 0, 39, 0, 0, 39, 45, 0, 0, ["soda", "pop", "coke"]),
    ("diet-cola", "Diet cola", "Drinks", "1 can (12 fl oz)", 355, 0, 0, 0, 0, 0, 0, 40, 0, 0, ["diet soda"]),
    ("sports-drink", "Sports drink", "Drinks", "20 fl oz", 591, 140, 0, 36, 0, 0, 34, 270, 0, 0, []),
    ("orange-juice", "Orange juice", "Drinks", "1 cup", 248, 112, 1.7, 25.8, 0.5, 0.5, 20.8, 2, 0, 0, ["juice", "oj"]),
    ("apple-juice", "Apple juice", "Drinks", "1 cup", 248, 114, 0.2, 28, 0.3, 0.5, 24, 10, 0, 0, []),
    ("fruit-smoothie", "Fruit smoothie", "Drinks", "16 fl oz", 480, 260, 3, 62, 1, 4, 50, 40, 0, 0, ["smoothie"]),
    ("beer", "Beer, regular", "Drinks", "12 fl oz", 356, 153, 1.6, 12.6, 0, 0, 0, 14, 0, 0, []),
    ("red-wine", "Red wine", "Drinks", "5 fl oz", 147, 125, 0.1, 3.8, 0, 0, 0.9, 6, 0, 0, ["wine"]),
    # --- Fats and condiments ---
    ("butter", "Butter, salted", "Condiments", "1 tbsp", 14, 102, 0.1, 0, 11.5, 0, 0, 91, 0, 0, []),
    ("olive-oil", "Olive oil", "Condiments", "1 tbsp", 13.5, 119, 0, 0, 13.5, 0, 0, 0, 0, 0, ["oil"]),
    ("mayonnaise", "Mayonnaise", "Condiments", "1 tbsp", 14, 94, 0.1, 0.1, 10.3, 0, 0.1, 88, 0, 0, ["mayo"]),
    ("ketchup", "Ketchup", "Condiments", "1 tbsp", 17, 17, 0.2, 4.5, 0, 0, 3.7, 150, 0, 0, []),
    ("ranch-dressing", "Ranch dressing", "Condiments", "2 tbsp", 30, 129, 0.4, 1.8, 13.4, 0, 1.4, 270, 0, 0, ["dressing"]),
    ("soy-sauce", "Soy sauce", "Condiments", "1 tbsp", 16, 9, 1.3, 0.8, 0.1, 0.1, 0.1, 880, 0, 0, []),
    ("jam", "Jam or jelly", "Condiments", "1 tbsp", 20, 56, 0, 13.8, 0, 0, 9.7, 6, 0, 0, ["jelly"]),
    ("honey", "Honey", "Condiments", "1 tbsp", 21, 64, 0, 17.3, 0, 0, 17.2, 1, 0, 0, []),
    ("table-salt", "Table salt", "Condiments", "1/4 teaspoon", 1.5, 0, 0, 0, 0, 0, 0, 575, 0, 0, ["salt"]),
]

FOOD_FIELDS = ("id", "name", "category", "serving", "serving_grams", "kcal", "protein_g", "carbs_g", "fat_g",
               "fiber_g", "sugar_g", "sodium_mg", "veg_servings", "water_ml", "aliases")
FOODS: list[dict] = [dict(zip(FOOD_FIELDS, row)) for row in _F]

# Nutrients summed per item and per day.
NUTRIENTS = ("kcal", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sodium_mg", "veg_servings", "water_ml")


# --- Daily targets -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    nutrient: str
    label: str
    unit: str
    kind: str          # 'max' (stay under) | 'min' (reach at least)
    value: float
    source: str


DGA = "Dietary Guidelines for Americans, 2020-2025"
FDA_DV = "FDA Daily Values for nutrition labels (2,000-calorie reference)"

DEFAULT_TARGETS: dict[str, Target] = {t.nutrient: t for t in [
    Target("sodium_mg", "Sodium", "mg", "max", 2300, DGA),
    Target("fiber_g", "Fiber", "g", "min", 28, FDA_DV),
    Target("sugar_g", "Sugar", "g", "max", 50, FDA_DV + " (added sugars; this log counts all sugars)"),
    Target("protein_g", "Protein", "g", "min", 50, FDA_DV),
    Target("fat_g", "Fat", "g", "max", 78, FDA_DV),
    Target("kcal", "Calories", "kcal", "max", 2000, FDA_DV + ". A general reference, not a personal calorie goal"),
    Target("veg_servings", "Vegetable servings", "servings", "min", 5, "MyPlate, USDA (about 2.5 cup-equivalents a day)"),
    Target("water_ml", "Water and plain drinks", "ml", "min", 1900, "About 8 glasses a day; food and other drinks add more"),
]}

# With raised blood pressure on record, the lower sodium limit.
HYPERTENSION_SODIUM = 1500
HYPERTENSION_SOURCE = "American Heart Association: ideal limit of 1,500 mg a day for most adults, especially with high blood pressure"


# --- Tip library ------------------------------------------------------------------------------------------
# Static, sourced, plain-language education. Picked by weekly pattern; never generated.

TIPS: dict[str, list[dict[str, str]]] = {
    "sodium_high": [
        {"text": "Most sodium comes from packaged, restaurant and deli foods rather than the salt shaker. "
                 "Sandwiches, pizza, soups and cured meats are the biggest sources for many people.",
         "source": "CDC, Top 10 sources of sodium", "url": "https://www.cdc.gov/salt/sodium-sources/index.html"},
        {"text": "Compare labels and pick the version with less sodium. 5% Daily Value or less per serving is low; "
                 "20% or more is high.",
         "source": "FDA, Sodium in your diet", "url": "https://www.fda.gov/food/nutrition-education-resources-materials/sodium-your-diet"},
        {"text": "Rinsing canned beans and vegetables can remove some of the sodium. Herbs, spices, lemon and "
                 "vinegar add flavor without salt.",
         "source": "American Heart Association, How to reduce sodium", "url": "https://www.heart.org/en/healthy-living/healthy-eating/eat-smart/sodium"},
    ],
    "fiber_low": [
        {"text": "Beans, lentils, whole grains, vegetables, fruit and nuts all add fiber. Swapping white bread or "
                 "rice for whole-grain versions is an easy start.",
         "source": DGA, "url": "https://www.dietaryguidelines.gov/"},
        {"text": "Add fiber gradually and drink water with it, so your body has time to adjust.",
         "source": "MedlinePlus, Dietary fiber", "url": "https://medlineplus.gov/ency/article/002470.htm"},
    ],
    "sugar_high": [
        {"text": "Sweetened drinks are the largest source of added sugars for many adults. Water, sparkling water "
                 "or unsweetened tea are simple swaps.",
         "source": "CDC, Get the facts: added sugars", "url": "https://www.cdc.gov/nutrition/php/data-research/added-sugars.html"},
    ],
    "veg_low": [
        {"text": "Try adding one vegetable to a meal you already eat, such as spinach in eggs, peppers in a "
                 "sandwich, or a side salad with dinner. Frozen and canned (low-sodium) vegetables count too.",
         "source": "MyPlate, USDA", "url": "https://www.myplate.gov/eat-healthy/vegetables"},
    ],
    "protein_low": [
        {"text": "Spread protein across the day: eggs or yogurt at breakfast, beans, fish, chicken or tofu at lunch "
                 "and dinner.",
         "source": DGA, "url": "https://www.dietaryguidelines.gov/"},
    ],
    "water_low": [
        {"text": "Keep a glass or bottle of water within reach and drink with each meal. Needs rise in hot weather "
                 "and with exercise.",
         "source": "CDC, About water and healthier drinks", "url": "https://www.cdc.gov/healthy-weight-growth/water-healthy-drinks/index.html"},
    ],
    "on_track": [
        {"text": "Your week looks balanced against your targets. Variety across the food groups helps you keep "
                 "it that way.",
         "source": DGA, "url": "https://www.dietaryguidelines.gov/"},
    ],
}
