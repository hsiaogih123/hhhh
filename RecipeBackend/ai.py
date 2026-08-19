import json
import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

INGREDIENT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "amount": {"type": "string"},
    },
    "required": ["name", "amount"],
}

NUTRITION_FACTS_SCHEMA = {
    "type": "object",
    "properties": {
        "protein": {"type": "string"},
        "carbs": {"type": "string"},
        "fat": {"type": "string"},
        "fiber": {"type": "string"},
        "sodium": {"type": "string"},
    },
    "required": ["protein", "carbs", "fat", "fiber", "sodium"],
}

RECIPE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "cooking_time": {"type": "string"},
        "difficulty": {"type": "string"},
        "calories": {"type": "string"},
        "equipment": {
            "type": "array",
            "items": {"type": "string"},
        },
        "ingredients": {
            "type": "array",
            "items": INGREDIENT_SCHEMA,
        },
        "steps": {
            "type": "array",
            "items": {"type": "string"},
        },
        "tip": {"type": "string"},
        "nutrition_facts": NUTRITION_FACTS_SCHEMA,
        "english_image_prompt": {"type": "string"},
    },
    "required": [
        "title",
        "description",
        "cooking_time",
        "difficulty",
        "calories",
        "equipment",
        "ingredients",
        "steps",
        "tip",
        "nutrition_facts",
        "english_image_prompt",
    ],
}

RECIPE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "is_valid_ingredients": {"type": "boolean"},
        "message": {"type": "string"},
        "recipes": {
            "type": "array",
            "items": RECIPE_ITEM_SCHEMA,
            "minItems": 0,
            "maxItems": 5,
        },
    },
    "required": ["is_valid_ingredients", "message", "recipes"],
}


def generate_recipe_from_ai(
    ingredients: str,
    style: str = "",
    cooking_time: str = "不限",
    portion_size: str = "2~3人份",
    extra_prefs: str = "",
) -> dict:
    style_text = style if style else "不限風格"
    cooking_time_text = cooking_time if cooking_time else "不限"
    portion_size_text = portion_size if portion_size else "2~3人份"
    extra_prefs_text = (extra_prefs or "").strip()
    extra_prefs_block = ""
    if extra_prefs_text:
        extra_prefs_block = f"""
【專屬客製化要求】 使用者特別交代了以下細節：『 {extra_prefs_text} 』。請你務必在設計食譜、挑選食材與調味時，嚴格遵守這個限制（例如：若提到不吃某物，絕對不可出現在食材清單中；若提到口味，請調整調味料比例）。
"""
    prompt = f"""在開始構思食譜前，請先檢查使用者提供的『食材清單』。如果裡面包含明顯不可食用、有毒、或非食物的物品（例如：石頭、鞋子、塑膠、文具等），請將 is_valid_ingredients 設為 false，並在 message 欄位寫下一句幽默的提醒（例如：『等等，鞋子不能拿來煮湯啦！請輸入真正的食物。』），此時 recipes 陣列請留空。若食材皆正常，則將 is_valid_ingredients 設為 true，message 留空，並依下方規則產出食譜。

【最高指導原則：食材不可拆分】
你所發想的每一道食譜，都必須完全包含使用者所輸入的『所有食材』！絕對不允許將使用者提供的食材拆分或分配到不同的食譜中。每一道菜都必須是所有輸入食材的綜合應用（你可以自行補充調味料或其他輔助食材，但使用者點名的食材一個都不能少）。
{extra_prefs_block}
你是一位專業廚師。請嚴格評估食材組合的難易度來決定食譜數量：

如果是常見、百搭的食材（如雞蛋、番茄、豬肉等），請務必產出剛好 5 道料理。

如果是普通組合，產出 3 到 4 道料理。

如果是極度困難或衝突的組合（如巧克力配大蒜），請產出 2 道料理。
絕對不能每次都固定產出 4 道，請務必依據上述規則給出 2、3、4 或 5 道食譜。

料理需截然不同且符合指定風格（例如：主食、湯品、熱炒、創意小點等）。

請嚴格遵守使用者指定的『烹調時間限制』：【 {cooking_time_text} 】。如果要求 15 分鐘內，請務必設計步驟極簡、易熟食材的快手料理；如果是 30 分鐘以上，可以設計燉煮或烤箱料理。並且，食譜資料結構中的『預估時間 (cooking_time)』欄位，其數值必須合理對應這個時間限制。

請依照使用者指定的『份量』：【 {portion_size_text} 】來精準調配食譜中的『食材與調味料的用量』。
請注意，不論使用者選擇幾人份，食譜所需的食材用量請依照總份量給出，但 nutrition_facts (營養素表) 的數值請統一以『單人份(1人份)』為基準來計算，並在前端標示清楚。

食材：{ingredients}
料理風格：{style_text}
烹調時間限制：{cooking_time_text}
份量：{portion_size_text}
進階客製化：{extra_prefs_text or "無"}

必須回傳 JSON 格式，不要包含任何其他文字或 markdown 標記。
頂層結構必須是：
{{
  "is_valid_ingredients": true 或 false,
  "message": "無效食材時的幽默提醒，有效時請留空字串",
  "recipes": [ 2 到 5 道食譜 ] 或 []
}}

當 is_valid_ingredients 為 true 時，每個食譜物件必須包含以下欄位：
- title: 食譜名稱（字串）
- description: 簡短誘人介紹（字串）
- cooking_time: 烹調時間（字串，例如「20 分鐘」），必須符合上述時間限制
- difficulty: 難易度（字串，例如「簡單」「中等」「進階」）
- calories: 熱量估計（字串，例如「約 380 kcal」）
- equipment: 所需廚具字串陣列。請分析這道菜需要的廚房設備或特定廚具（例如：平底鍋、烤箱、氣炸鍋、湯鍋、打蛋器等），並以陣列形式放入 equipment 欄位中
- ingredients: 食材陣列，每個元素為 {{"name": "食材名", "amount": "份量與處理方式"}}
- steps: 烹調步驟（字串陣列）
- tip: 私廚秘訣（字串）
- nutrition_facts: 營養素物件，格式為 {{"protein": "25g", "carbs": "40g", "fat": "12g", "fiber": "5g", "sodium": "300mg"}}
- english_image_prompt: 用於 AI 圖片生成的『英文描述』。必須是純英文，請專注於食物的外觀、食材與烹飪方式。例如：'Taiwanese tomato and egg stir-fry with bright red tomatoes and fluffy yellow scrambled eggs, highly detailed food photography'

請為這道料理產生一句用於 AI 圖片生成的『英文描述 (english_image_prompt)』。必須是純英文，請專注於食物的外觀、食材與烹飪方式。例如：'Taiwanese tomato and egg stir-fry with bright red tomatoes and fluffy yellow scrambled eggs, highly detailed food photography'。

請以『單人份』為基準，為這道料理預估詳細的營養素數值，並填入 nutrition_facts 物件中（包含蛋白質 protein、碳水化合物 carbs、脂肪 fat、膳食纖維 fiber、鈉含量 sodium，請附上 g 或 mg 單位）。

請確保各道菜標題互不重複，且每一道菜都必須完整使用使用者提供的『所有食材』（再次強調：禁止拆分食材到不同食譜）。"""

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_json_schema": RECIPE_JSON_SCHEMA,
        },
    )

    result = json.loads(response.text)
    is_valid = bool(result.get("is_valid_ingredients", True))
    message = result.get("message") or ""
    recipes = result.get("recipes")

    if not is_valid:
        return {
            "is_valid_ingredients": False,
            "message": message
            or "等等，這些好像不太能拿來下廚喔！請輸入真正的食物。",
            "recipes": [],
        }

    if not isinstance(recipes, list) or not (2 <= len(recipes) <= 5):
        raise ValueError("AI must return between 2 and 5 recipes")

    required_fields = {
        "title",
        "description",
        "cooking_time",
        "difficulty",
        "calories",
        "equipment",
        "ingredients",
        "steps",
        "tip",
        "nutrition_facts",
        "english_image_prompt",
    }
    for recipe in recipes:
        if not required_fields.issubset(recipe):
            raise ValueError("AI recipe missing required fields")

    return {
        "is_valid_ingredients": True,
        "message": "",
        "recipes": recipes,
    }


def answer_recipe_question(recipe_context: str, question: str) -> str:
    prompt = f"""你是一位經驗豐富且充滿熱情的五星級主廚。使用者目前正在製作以下這道料理：
【食譜內容】
{recipe_context}

【使用者的問題 / 遇到的狀況】
{question}

請針對使用者的問題，給出簡短、實用、具體且能立刻執行的『補救措施』或『替代方案』。語氣要鼓勵且專業，不要超過 150 字。"""

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
    )
    answer = (response.text or "").strip()
    if not answer:
        raise ValueError("AI returned an empty answer")
    return answer
