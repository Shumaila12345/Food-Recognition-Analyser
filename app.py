import os
import json
import requests
import streamlit as st
import plotly.graph_objects as go
from dotenv import load_dotenv
from google import genai
from google.genai import types
from database import init_db, save_analysis, get_all_history, delete_history_item, clear_all_history

# ---------- SETUP ----------
load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
usda_api_key = os.environ["USDA_API_KEY"]

st.set_page_config(page_title="AI Food Analyzer", page_icon="🍽️", layout="centered")
init_db()

# ---------- GLOBAL STYLING ----------
st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
    html, body, [class*="css"] { font-family: 'Poppins', sans-serif; }

    .stApp {
        background: linear-gradient(180deg, #FDFCF7 0%, #F1F8F3 100%);
    }

    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #14421B 0%, #2E7D32 100%);
    }
    section[data-testid="stSidebar"] * { color: #FFFFFF !important; }

    .main-title { font-size: 2.2rem; font-weight: 800; color: #14421B; margin-bottom: 0; }
    .subtitle { color: #555; margin-bottom: 1.5rem; font-size: 1.05rem; }

    .hero-box {
        background: linear-gradient(135deg, #81C784 0%, #FFB74D 100%);
        border-radius: 24px; padding: 45px 30px; margin-bottom: 25px; text-align: center;
        box-shadow: 0 10px 30px rgba(0,0,0,0.12);
    }
    .hero-box .main-title { color: #14311A; }
    .hero-box .subtitle { color: #2E2E2E; font-weight: 500; }

    .feature-card {
        background-color: #FFFFFF; border-radius: 18px; padding: 24px 16px;
        box-shadow: 0 6px 18px rgba(0,0,0,0.07);
        margin-bottom: 12px; text-align: center; font-size: 0.95rem;
        transition: transform 0.2s ease;
    }
    .feature-card:hover { transform: translateY(-5px); }
    .feature-icon-circle {
        width: 56px; height: 56px; border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        margin: 0 auto 10px auto; font-size: 1.6rem;
    }

    .food-card {
        background-color: #FFFFFF; border-radius: 18px; padding: 20px 24px;
        margin-bottom: 8px; border-left: 7px solid #4CAF50;
        box-shadow: 0 5px 16px rgba(0,0,0,0.06);
    }
    .food-card-low { border-left: 7px solid #FFA726; }
    .food-name { font-size: 1.2rem; font-weight: 700; color: #1A1A1A; }
    .confidence-pill {
        display: inline-block; padding: 3px 12px; border-radius: 999px;
        font-size: 0.78rem; font-weight: 600; margin-top: 4px;
    }
    .pill-high { background-color: #E8F5E9; color: #2E7D32; }
    .pill-low { background-color: #FFF3E0; color: #E65100; }

    .total-box {
        background: linear-gradient(135deg, #1B5E20 0%, #388E3C 100%);
        border-radius: 22px; padding: 28px; margin-top: 24px;
        box-shadow: 0 10px 26px rgba(0,0,0,0.15);
    }
    .total-box h2, .total-box p { color: white !important; }

    .disclaimer {
        font-size: 0.8rem; color: #888; margin-top: 20px; font-style: italic;
        background-color: #FAFAFA; padding: 12px 16px; border-radius: 12px;
    }

    .stButton>button {
        border-radius: 12px; font-weight: 700; border: none;
        background: linear-gradient(135deg, #43A047, #1B5E20);
        color: white; padding: 12px 0; font-size: 1rem;
        transition: opacity 0.2s ease;
    }
    .stButton>button:hover { opacity: 0.88; color: white; }

    [data-testid="stFileUploader"] {
        background-color: #FFFFFF; border-radius: 16px; padding: 12px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
    }
</style>
""", unsafe_allow_html=True)

# ---------- SIDEBAR NAVIGATION ----------
if "page" not in st.session_state:
    st.session_state["page"] = "Home"

with st.sidebar:
    st.markdown("## 🍽️ Food Analyzer")
    page = st.radio("Navigate", ["Home", "Analyze Food", "History", "About"],
                     index=["Home", "Analyze Food", "History", "About"].index(st.session_state["page"]))
    st.session_state["page"] = page


# ---------- SHARED FUNCTIONS ----------

def detect_food(image_bytes):
    """Returns a list of detected foods, or None if the AI call itself failed
    (e.g. network issue, invalid response) — distinct from an empty list,
    which means the call worked but no food was found."""
    prompt = """Identify all food items visible in this image with SPECIFIC names 
    (e.g. "chocolate brownie" not "dessert", "grilled chicken" not "meat").
    Avoid vague or generic category names.
    For each item, give a confidence score from 0-100.
    Respond ONLY in this exact JSON format, nothing else:
    [{"food": "Grilled Chicken", "confidence": 87}]"""

    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=[types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"), prompt]
        )
    except Exception:
        # Covers network errors, API downtime, invalid API key, etc.
        return None

    try:
        raw_text = response.text.strip().replace("```json", "").replace("```", "").strip()
        detected = json.loads(raw_text)
    except (json.JSONDecodeError, AttributeError):
        # Gemini sometimes returns text that isn't valid JSON (rare, but possible)
        return None

    seen, unique_detected = set(), []
    for item in detected:
        if item.get('food') and item['food'] not in seen:
            seen.add(item['food'])
            unique_detected.append(item)
    return unique_detected


def get_nutrition(food_name):
    """Returns nutrition dict, or None if either no match was found OR the
    API call itself failed (network issue, timeout, etc.)."""
    url = "https://api.nal.usda.gov/fdc/v1/foods/search"
    params = {"query": food_name, "api_key": usda_api_key, "pageSize": 1}
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
    except (requests.exceptions.RequestException, ValueError):
        return None

    if not data.get("foods"):
        return None

    top_result = data["foods"][0]
    nutrients = {}
    for n in top_result.get("foodNutrients", []):
        name, value = n.get("nutrientName", ""), n.get("value", 0)
        if "Energy" in name: nutrients["calories"] = value
        elif "Protein" in name: nutrients["protein"] = value
        elif "Carbohydrate" in name: nutrients["carbs"] = value
        elif "Total lipid (fat)" in name: nutrients["fat"] = value
        elif "Fiber" in name: nutrients["fiber"] = value
    nutrients["base_serving_g"] = 100
    return nutrients


def scale_nutrition_to_portion(nutrition, portion_grams):
    base = nutrition.get("base_serving_g", 100)
    scale_factor = portion_grams / base
    return {k: round(v * scale_factor, 1) for k, v in nutrition.items() if k != "base_serving_g"}


def macro_donut(calories, protein, carbs, fat):
    """Donut chart showing protein/carbs/fat split, with total calories in the center."""
    values = [max(protein, 0.01), max(carbs, 0.01), max(fat, 0.01)]
    fig = go.Figure(data=[go.Pie(
        labels=["Protein", "Carbs", "Fat"],
        values=values,
        hole=0.68,
        marker=dict(colors=["#43A047", "#FFA726", "#EF5350"], line=dict(color="white", width=2)),
        textinfo="label",
        textfont=dict(size=11, color="white"),
        showlegend=False
    )])
    fig.update_layout(
        margin=dict(t=10, b=10, l=10, r=10),
        height=200,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        annotations=[dict(
            text=f"<b>{calories}</b><br>kcal",
            x=0.5, y=0.5, font_size=15, font_color="#222", showarrow=False
        )]
    )
    return fig


def calorie_gauge(total_calories):
    """Big circular gauge showing total meal calories, with its OWN solid background
    (doesn't rely on an outer div, since Streamlit can't nest charts inside markdown divs)."""
    max_range = max(2500, total_calories * 1.3)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=total_calories,
        number={"suffix": " kcal", "font": {"size": 36, "color": "white"}},
        gauge={
            "axis": {"range": [0, max_range], "tickcolor": "rgba(255,255,255,0.5)",
                     "tickfont": {"color": "rgba(255,255,255,0.7)", "size": 10}},
            "bar": {"color": "#FFB74D", "thickness": 0.3},
            "bgcolor": "rgba(255,255,255,0.12)",
            "borderwidth": 0,
        },
        domain={"x": [0, 1], "y": [0, 1]}
    ))
    fig.update_layout(
        height=260,
        margin=dict(t=40, b=20, l=40, r=40),
        paper_bgcolor="#1B5E20",  # solid color matching the total-box theme
        font={"color": "white"}
    )
    return fig


def nutrient_stat_boxes(stats, dark_mode=False):
    """Renders a row of colored icon stat boxes instead of plain text numbers.
    stats: list of (icon, label, value) tuples.
    Each box carries its OWN solid background (not transparent) so it stays
    readable no matter what it's placed on top of."""
    box_bg = "#2E7D32" if dark_mode else "#FFFFFF"
    label_color = "rgba(255,255,255,0.85)" if dark_mode else "#666"
    value_color = "#FFFFFF" if dark_mode else "#1A1A1A"
    shadow = "0 3px 10px rgba(0,0,0,0.15)" if dark_mode else "0 3px 10px rgba(0,0,0,0.06)"

    html = '<div style="display:flex; gap:10px; flex-wrap:wrap; margin:10px 0;">'
    for icon, label, value in stats:
        html += f'''
        <div style="flex:1; min-width:85px; background:{box_bg}; border-radius:14px;
                    padding:12px 8px; text-align:center; box-shadow:{shadow};">
            <div style="font-size:1.3rem;">{icon}</div>
            <div style="font-size:0.72rem; color:{label_color}; font-weight:600; margin-top:2px;">{label}</div>
            <div style="font-size:1.05rem; font-weight:800; color:{value_color};">{value}</div>
        </div>'''
    html += '</div>'
    return html


# ================= HOME PAGE =================
if st.session_state["page"] == "Home":
    st.markdown("""
    <div class="hero-box">
        <h1 class="main-title">🍽️ AI Food Recognition & Nutrition Analyzer</h1>
        <p class="subtitle">Snap or upload a photo of your meal — get instant AI-powered nutrition estimates.</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        <div class="feature-card">
            <div class="feature-icon-circle" style="background:#E8F5E9;">📸</div>
            <b>Upload or Capture</b><br>Take a photo or upload one from your device
        </div>""", unsafe_allow_html=True)
    with col2:
        st.markdown("""
        <div class="feature-card">
            <div class="feature-icon-circle" style="background:#FFF3E0;">🤖</div>
            <b>AI Detection</b><br>Identifies multiple foods with confidence scores
        </div>""", unsafe_allow_html=True)
    with col3:
        st.markdown("""
        <div class="feature-card">
            <div class="feature-icon-circle" style="background:#FFEBEE;">📊</div>
            <b>Nutrition Breakdown</b><br>Calories, protein, carbs, fat & fiber per item
        </div>""", unsafe_allow_html=True)

    st.write("")
    if st.button("🚀 Start Analyzing", use_container_width=True):
        st.session_state["page"] = "Analyze Food"
        st.rerun()


# ================= ANALYZE FOOD PAGE =================
elif st.session_state["page"] == "Analyze Food":
    st.markdown('<p class="main-title">Analyze Your Food</p>', unsafe_allow_html=True)
    st.markdown('<p class="subtitle">Upload an image or take a photo directly</p>', unsafe_allow_html=True)

    input_method = st.radio("Choose input method", ["Upload Image", "Take Photo"], horizontal=True)

    # Used to force the file_uploader widget to reset when "Remove Image" is clicked
    if "uploader_key" not in st.session_state:
        st.session_state["uploader_key"] = 0

    image_bytes = None
    if input_method == "Upload Image":
        uploaded_file = st.file_uploader("Upload a food image (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"],
                                          key=f"uploader_{st.session_state['uploader_key']}")
        if uploaded_file:
            st.image(uploaded_file, caption="Preview", use_container_width=True)
            if st.button("❌ Remove Image"):
                st.session_state["uploader_key"] += 1  # changes the widget's key, forcing a fresh empty uploader
                st.rerun()
            image_bytes = uploaded_file.read()
    else:
        camera_file = st.camera_input("Take a photo of your food")
        if camera_file:
            image_bytes = camera_file.read()

    if image_bytes and st.button("🔍 Analyze Food", use_container_width=True):
        with st.spinner("Analyzing image..."):
            detected_foods = detect_food(image_bytes)

        if detected_foods is None:
            st.error("⚠️ We couldn't analyze this image right now. This could be a network "
                      "issue or a temporary problem with the AI service. Please try again.")
        elif len(detected_foods) == 0:
            st.warning("🤔 We couldn't confidently identify any food in this image. "
                        "Please upload a clearer food photo.")
        else:
            st.session_state["detected_foods"] = detected_foods
            st.session_state["portions"] = {item["food"]: 100 for item in detected_foods}

    # ---------- RESULTS ----------
    if "detected_foods" in st.session_state:
        detected_foods = st.session_state["detected_foods"]
        st.subheader("Detected Foods")
        total = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0}

        for item in detected_foods:
            food, conf = item["food"], item["confidence"]
            is_low = conf < 80
            card_class = "food-card food-card-low" if is_low else "food-card"
            pill_class = "confidence-pill pill-low" if is_low else "confidence-pill pill-high"
            icon = "⚠️" if is_low else "✅"

            left, right = st.columns([2, 1])

            with left:
                st.markdown(f"""
                <div class="{card_class}">
                    <span class="food-name">{icon} {food}</span><br>
                    <span class="{pill_class}">Confidence: {conf}%{" — The AI is not confident about this result. Please verify." if is_low else ""}</span>
                </div>""", unsafe_allow_html=True)

                portion = st.number_input(f"Serving size for {food} (grams)", min_value=1, max_value=2000,
                                           value=st.session_state["portions"].get(food, 100), step=10,
                                           key=f"portion_{food}")
                st.session_state["portions"][food] = portion

            nutrition = get_nutrition(food)
            if nutrition:
                scaled = scale_nutrition_to_portion(nutrition, portion)
                save_analysis(food, conf, portion, scaled)
                with right:
                    fig = macro_donut(scaled["calories"], scaled["protein"], scaled["carbs"], scaled["fat"])
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

                stats = [
                    ("🔥", "Calories", f"{scaled['calories']}"),
                    ("💪", "Protein", f"{scaled['protein']}g"),
                    ("🌾", "Carbs", f"{scaled['carbs']}g"),
                    ("🥑", "Fat", f"{scaled['fat']}g"),
                    ("🌿", "Fiber", f"{scaled['fiber']}g"),
                ]
                st.markdown(nutrient_stat_boxes(stats), unsafe_allow_html=True)
                for k in total: total[k] += scaled.get(k, 0)
            else:
                st.info(f"ℹ️ No nutrition data found for '{food}' in the USDA database. "
                         f"This can happen for regional or mixed dishes. Try a more common name, "
                         f"or note this as a known limitation in your report.")
            st.divider()

        # ---------- TOTAL MEAL NUTRITION ----------
        # Each piece below (header, gauge, stat boxes) carries its OWN solid background
        # color, rather than trying to wrap them all in one outer div — Streamlit renders
        # every st.markdown/st.plotly_chart call as a separate block, so an open <div> in
        # one call does NOT actually contain elements from later calls.
        st.markdown(
            '<div style="background:linear-gradient(135deg,#1B5E20,#388E3C); '
            'border-radius:22px; padding:20px 20px 10px 20px; margin-top:24px;">'
            '<h2 style="text-align:center; color:white; margin:0;">📊 Total Meal Nutrition</h2>'
            '</div>', unsafe_allow_html=True
        )

        gauge_fig = calorie_gauge(round(total["calories"], 1))
        st.plotly_chart(gauge_fig, use_container_width=True, config={"displayModeBar": False})

        total_stats = [
            ("💪", "Protein", f"{round(total['protein'],1)}g"),
            ("🌾", "Carbs", f"{round(total['carbs'],1)}g"),
            ("🥑", "Fat", f"{round(total['fat'],1)}g"),
            ("🌿", "Fiber", f"{round(total['fiber'],1)}g"),
        ]
        st.markdown(nutrient_stat_boxes(total_stats, dark_mode=True), unsafe_allow_html=True)

        st.markdown('<p class="disclaimer">⚠️ Nutritional values are estimates and may vary depending on '
                     'ingredients, preparation method, and portion size. This is not a medically accurate '
                     'nutrition system.</p>', unsafe_allow_html=True)

        if st.button("🔄 Analyze Another Image"):
            del st.session_state["detected_foods"]
            del st.session_state["portions"]
            st.rerun()


# ================= HISTORY PAGE =================
elif st.session_state["page"] == "History":
    st.markdown('<p class="main-title">📅 Analysis History</p>', unsafe_allow_html=True)
    st.markdown('<p class="subtitle">Your past food analyses</p>', unsafe_allow_html=True)

    history = get_all_history()

    if not history:
        st.info("No analysis history yet. Analyze a food photo to see it appear here.")
    else:
        if st.button("🗑️ Clear All History"):
            clear_all_history()
            st.rerun()

        for row in history:
            (item_id, food, confidence, serving_size, calories,
             protein, carbs, fat, fiber, created_at) = row

            st.markdown(f"""
            <div class="food-card">
                <span class="food-name">{food}</span><br>
                <span class="confidence-badge">📅 {created_at} &nbsp;|&nbsp; Serving: {serving_size}g &nbsp;|&nbsp; Confidence: {round(confidence)}%</span>
            </div>""", unsafe_allow_html=True)

            stats = [
                ("🔥", "Calories", f"{calories}"),
                ("💪", "Protein", f"{protein}g"),
                ("🌾", "Carbs", f"{carbs}g"),
                ("🥑", "Fat", f"{fat}g"),
                ("🌿", "Fiber", f"{fiber}g"),
            ]
            st.markdown(nutrient_stat_boxes(stats), unsafe_allow_html=True)

            if st.button(f"Delete this entry", key=f"delete_{item_id}"):
                delete_history_item(item_id)
                st.rerun()

            st.divider()


# ================= ABOUT PAGE =================
elif st.session_state["page"] == "About":
    st.markdown('<p class="main-title">About This Project</p>', unsafe_allow_html=True)
    st.write("""
    This AI-powered web app analyzes food images and provides estimated nutritional information.
    
    **How it works:**
    1. Upload or capture a food photo
    2. Google Gemini Vision AI identifies the food items with confidence scores
    3. USDA FoodData Central provides nutrition data per food
    4. Values are scaled to your entered serving size
    5. A total meal nutrition summary is calculated
    
    **Important:** Results are estimates only. Accuracy depends on image quality, 
    lighting, and how visually distinct the food is. Nutrition values may vary 
    based on actual ingredients and preparation method.
    """)
