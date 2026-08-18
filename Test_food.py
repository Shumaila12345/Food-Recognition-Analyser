import os
import json
import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load your API keys from the .env file
load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
usda_api_key = os.environ["USDA_API_KEY"]

# ---------- STEP 1: Read the test image ----------
with open("test_food.jpeg", "rb") as f:
    image_bytes = f.read()

# ---------- STEP 2: Ask Gemini to identify the food ----------
prompt = """Identify all food items visible in this image with SPECIFIC names 
(e.g. "chocolate brownie" not "dessert", "grilled chicken" not "meat", 
"basmati rice" not just "rice").
Avoid vague or generic category names.
For each item, give a confidence score from 0-100.
Respond ONLY in this exact JSON format, nothing else:
[{"food": "Grilled Chicken", "confidence": 87}]"""

response = client.models.generate_content(
    model="gemini-3.5-flash-lite",
    contents=[
        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
        prompt
    ]
)

# Clean up Gemini's response (remove ```json fencing) and parse it
raw_text = response.text.strip()
raw_text = raw_text.replace("```json", "").replace("```", "").strip()
detected_foods = json.loads(raw_text)

# ---------- STEP 3: Print detected foods ----------
print("Parsed foods:")
for item in detected_foods:
    print(f"- {item['food']} ({item['confidence']}%)")

# ---------- STEP 4: Print with low-confidence warnings ----------
print("\n--- Detected Foods (with confidence check) ---")
for item in detected_foods:
    food = item['food']
    conf = item['confidence']
    if conf < 80:
        print(f"⚠️  {food} — {conf}% (low confidence, please verify)")
    else:
        print(f"✅ {food} — {conf}%")


# Extract just the food names for the nutrition lookup, removing duplicates
food_names = list(dict.fromkeys(item['food'] for item in detected_foods))
print("\nNames only (for USDA lookup):", food_names)

# ---------- STEP 5: USDA nutrition lookup (per 100g baseline) ----------
def get_nutrition(food_name):
    url = "https://api.nal.usda.gov/fdc/v1/foods/search"
    params = {
        "query": food_name,
        "api_key": usda_api_key,
        "pageSize": 1
    }
    response = requests.get(url, params=params)
    data = response.json()

    if not data.get("foods"):
        return None

    top_result = data["foods"][0]
    nutrients = {}
    for n in top_result.get("foodNutrients", []):
        name = n.get("nutrientName", "")
        value = n.get("value", 0)
        if "Energy" in name:
            nutrients["calories"] = value
        elif "Protein" in name:
            nutrients["protein"] = value
        elif "Carbohydrate" in name:
            nutrients["carbs"] = value
        elif "Total lipid (fat)" in name:
            nutrients["fat"] = value
        elif "Fiber" in name:
            nutrients["fiber"] = value

    nutrients["base_serving_g"] = 100  # USDA values are per 100g by default
    return nutrients


# ---------- STEP 5b: Recalculate nutrition for actual portion size ----------
def scale_nutrition_to_portion(nutrition, portion_grams):
    """Scales per-100g nutrition values to the user's actual serving size."""
    base = nutrition.get("base_serving_g", 100)
    scale_factor = portion_grams / base

    scaled = {}
    for key, value in nutrition.items():
        if key == "base_serving_g":
            continue
        scaled[key] = round(value * scale_factor, 1)

    scaled["serving_size_g"] = portion_grams
    return scaled


# ---------- STEP 6: Print nutrition per food, scaled to portion size ----------
# For now, manually testing with example portion sizes (grams)
# Later in Streamlit, users will type these in themselves
example_portions = {
    "Pizza": 150,
    "Chocolate Brownie": 80,
    "Vanilla Ice Cream": 100,
    "Chocolate Sauce": 30,
    "Sheer Khurma": 120,
    "Pistachio": 20,
    "Almond": 20
}

print("\n--- Nutrition Results (scaled to portion size) ---")
scaled_results = {}  # we'll reuse this in Step 7 instead of calling the API again
for name in food_names:
    nutrition = get_nutrition(name)
    portion = example_portions.get(name, 100)  # default 100g if not listed

    print(f"\n{name} (serving: {portion}g):")
    if nutrition:
        scaled = scale_nutrition_to_portion(nutrition, portion)
        scaled_results[name] = scaled
        for key, value in scaled.items():
            if key != "serving_size_g":
                print(f"  {key}: {value}")
    else:
        print("  No nutrition data found")
        scaled_results[name] = None


# ---------- STEP 7: Calculate and print TOTAL meal nutrition (using scaled values) ----------
def calculate_total_nutrition(scaled_results):
    total = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0}
    for name, nutrition in scaled_results.items():
        if nutrition:
            for key in total:
                total[key] += nutrition.get(key, 0)
    return total


meal_total = calculate_total_nutrition(scaled_results)

print("\n--- TOTAL MEAL NUTRITION (portion-adjusted) ---")
for key, value in meal_total.items():
    print(f"{key}: {round(value, 1)}")