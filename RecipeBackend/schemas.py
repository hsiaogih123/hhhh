from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserAuthSchema(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9]+$")
    password: str = Field(min_length=6, max_length=16)


class UserCreate(UserAuthSchema):
    pass


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str | None = None
    created_at: datetime


class UserUpdateRequest(BaseModel):
    old_password: str = Field(max_length=16)
    new_username: str | None = None
    new_password: str | None = Field(default=None, max_length=16)
    nickname: str | None = None


class Token(BaseModel):
    access_token: str
    token_type: str


class RecipeCreate(BaseModel):
    ingredients: str
    style: str = ""
    cooking_time: str = "不限"
    portion_size: str = "2~3人份"
    extra_prefs: str = ""


class RecipeIngredient(BaseModel):
    name: str
    amount: str = ""


class NutritionFacts(BaseModel):
    protein: str = ""
    carbs: str = ""
    fat: str = ""
    fiber: str = ""
    sodium: str = ""


class RecipeItem(BaseModel):
    title: str
    description: str = ""
    cooking_time: str = ""
    difficulty: str = ""
    calories: str = ""
    equipment: list[str] = Field(default_factory=list)
    ingredients: list[RecipeIngredient] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    tip: str = ""
    nutrition_facts: NutritionFacts = Field(default_factory=NutritionFacts)
    english_image_prompt: str = ""


class RecipeListResponse(BaseModel):
    id: int
    user_id: int
    created_at: datetime
    input_ingredients: str = ""
    style: str = ""
    recipes: list[RecipeItem]
    is_valid_ingredients: bool = True
    message: str = ""
    extra_prefs: str = ""


class RecipeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    content_json: dict | None
    user_id: int
    created_at: datetime


class RecipeQuestionRequest(BaseModel):
    recipe_context: str
    question: str


class RecipeQuestionResponse(BaseModel):
    answer: str


class ImageRequest(BaseModel):
    prompt: str  # 英文視覺提示詞
    style: str  # realistic 或 anime


class SyncRecipesRequest(BaseModel):
    recipes: list[dict] = Field(default_factory=list)
