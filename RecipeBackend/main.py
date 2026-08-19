from contextlib import asynccontextmanager
from datetime import datetime
import io
import os
import re

import requests
from dotenv import load_dotenv

# 載入 .env 檔案
load_dotenv()

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from ai import answer_recipe_question, generate_recipe_from_ai
from auth import (
    create_access_token,
    get_current_user,
    get_db,
    get_password_hash,
    require_current_user,
    verify_password,
)
from database import Base, engine
from models import Recipe, SavedRecipe, User
from schemas import (
    ImageRequest,
    RecipeCreate,
    RecipeItem,
    RecipeListResponse,
    RecipeQuestionRequest,
    RecipeQuestionResponse,
    RecipeResponse,
    SyncRecipesRequest,
    Token,
    UserAuthSchema,
    UserCreate,
    UserResponse,
    UserUpdateRequest,
)
import models  # noqa: F401 — register models with Base.metadata

router = APIRouter()

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9]+$")


def ensure_user_nickname_column() -> None:
    """Best-effort SQLite column add for existing DBs."""
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN nickname VARCHAR"))
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_user_nickname_column()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def read_root():
    return FileResponse("index.html")


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.username == user.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    db_user = User(
        username=user.username,
        hashed_password=get_password_hash(user.password),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.post("/login", response_model=Token)
def login(user_data: UserAuthSchema, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == user_data.username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="此帳戶不存在或已被移除",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="密碼錯誤",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    return Token(access_token=access_token, token_type="bearer")


@router.get("/users/me", response_model=UserResponse)
def get_current_user_profile(current_user: User = Depends(require_current_user)):
    return current_user


@router.put("/users/me", response_model=UserResponse)
def update_current_user_profile(
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    if not verify_password(payload.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="舊密碼不正確",
        )

    new_username = (payload.new_username or "").strip()
    if new_username and new_username != current_user.username:
        if not USERNAME_PATTERN.fullmatch(new_username):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="帳號只能包含英文和數字",
            )
        existing = (
            db.query(User)
            .filter(User.username == new_username, User.id != current_user.id)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="此帳號已被使用",
            )
        current_user.username = new_username

    if payload.nickname is not None:
        current_user.nickname = payload.nickname.strip() or None

    new_password = payload.new_password or ""
    if new_password:
        if len(new_password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="新密碼最少需要 6 個字元",
            )
        if len(new_password) > 16:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="密碼長度不可超過 16 位數！",
            )
        current_user.hashed_password = get_password_hash(new_password)

    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.delete("/users/me")
def delete_current_user(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    user_id = current_user.id

    # Remove favorites owned by this user
    db.query(SavedRecipe).filter(SavedRecipe.user_id == user_id).delete(
        synchronize_session=False
    )

    # Remove favorites that reference this user's recipes (avoid FK errors)
    user_recipe_ids = [
        recipe_id
        for (recipe_id,) in db.query(Recipe.id).filter(Recipe.user_id == user_id).all()
    ]
    if user_recipe_ids:
        db.query(SavedRecipe).filter(
            SavedRecipe.recipe_id.in_(user_recipe_ids)
        ).delete(synchronize_session=False)

    # Remove recipes created by this user
    db.query(Recipe).filter(Recipe.user_id == user_id).delete(synchronize_session=False)

    db.delete(current_user)
    db.commit()
    return {"message": "帳戶已成功刪除"}


@router.get("/recipes/history", response_model=list[RecipeResponse])
def get_recipe_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    recipes = (
        db.query(Recipe)
        .filter(Recipe.user_id == current_user.id)
        .order_by(Recipe.created_at.desc())
        .limit(10)
        .all()
    )
    return recipes


@router.post("/recipes/generate", response_model=RecipeListResponse)
def generate_recipe(
    recipe_data: RecipeCreate,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    try:
        ai_result = generate_recipe_from_ai(
            recipe_data.ingredients,
            recipe_data.style,
            recipe_data.cooking_time,
            recipe_data.portion_size,
            recipe_data.extra_prefs,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to generate recipe from AI: {exc}",
        ) from exc

    is_valid = bool(ai_result.get("is_valid_ingredients", True))
    message = ai_result.get("message") or ""
    recipes = ai_result.get("recipes") or []
    user_id = current_user.id if current_user else 0

    extra_prefs = recipe_data.extra_prefs or ""

    if not is_valid:
        return RecipeListResponse(
            id=0,
            user_id=user_id,
            created_at=datetime.utcnow(),
            input_ingredients=recipe_data.ingredients,
            style=recipe_data.style,
            recipes=[],
            is_valid_ingredients=False,
            message=message
            or "等等，這些好像不太能拿來下廚喔！請輸入真正的食物。",
            extra_prefs=extra_prefs,
        )

    # Guest / unauthenticated: generate only, never persist to history
    if current_user is None:
        return RecipeListResponse(
            id=0,
            user_id=0,
            created_at=datetime.utcnow(),
            input_ingredients=recipe_data.ingredients,
            style=recipe_data.style,
            recipes=[RecipeItem(**item) for item in recipes],
            is_valid_ingredients=True,
            message="",
            extra_prefs=extra_prefs,
        )

    first = recipes[0]
    style_label = recipe_data.style or "不限風格"

    db_recipe = Recipe(
        title=first["title"],
        description=f"為您配對 {len(recipes)} 道「{style_label}」食譜",
        content_json={
            "ingredients": recipe_data.ingredients,
            "style": recipe_data.style,
            "cooking_time": recipe_data.cooking_time,
            "portion_size": recipe_data.portion_size,
            "extra_prefs": extra_prefs,
            "recipes": recipes,
        },
        user_id=current_user.id,
    )
    db.add(db_recipe)
    db.commit()
    db.refresh(db_recipe)

    return RecipeListResponse(
        id=db_recipe.id,
        user_id=db_recipe.user_id,
        created_at=db_recipe.created_at,
        input_ingredients=recipe_data.ingredients,
        style=recipe_data.style,
        recipes=[RecipeItem(**item) for item in recipes],
        is_valid_ingredients=True,
        message="",
        extra_prefs=extra_prefs,
    )


@app.post("/api/recipes/sync")
def sync_guest_recipes(
    payload: SyncRecipesRequest,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
):
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    for item in payload.recipes:
        if not isinstance(item, dict):
            continue

        nested_recipes = item.get("recipes") or []
        if not nested_recipes and item.get("content_json"):
            nested_recipes = (item.get("content_json") or {}).get("recipes") or []

        style = item.get("style") or (item.get("content_json") or {}).get("style") or ""
        style_label = style or "不限風格"
        first = nested_recipes[0] if nested_recipes and isinstance(nested_recipes[0], dict) else {}
        title = (first.get("title") if first else None) or item.get("title") or "未命名食譜"
        description = item.get("description") or (
            f"為您配對 {len(nested_recipes) or 1} 道「{style_label}」食譜"
        )

        content_json = item.get("content_json")
        if not isinstance(content_json, dict):
            content_json = {
                "ingredients": item.get("input_ingredients") or item.get("ingredients") or "",
                "style": style,
                "cooking_time": item.get("cooking_time") or "不限",
                "portion_size": item.get("portion_size") or "2~3人份",
                "extra_prefs": item.get("extra_prefs") or "",
                "recipes": nested_recipes,
            }

        db.add(
            Recipe(
                title=title,
                description=description,
                content_json=content_json,
                user_id=current_user.id,
            )
        )

    db.commit()
    return {"message": "訪客食譜已成功同步至帳戶"}


@router.post("/recipe/question", response_model=RecipeQuestionResponse)
def ask_recipe_question(payload: RecipeQuestionRequest):
    question = (payload.question or "").strip()
    recipe_context = (payload.recipe_context or "").strip()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="請輸入問題",
        )
    if not recipe_context:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少食譜內容",
        )

    try:
        answer = answer_recipe_question(recipe_context, question)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to get answer from AI: {exc}",
        ) from exc

    return RecipeQuestionResponse(answer=answer)


@app.post("/api/recipe/image")
async def get_ai_image(request: ImageRequest):
    HF_TOKEN = "Bearer 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"

    headers = {"Authorization": HF_TOKEN}
    payload = {"inputs": request.prompt, "parameters": {"wait_for_model": True}}

    # 根據風格選擇不同模型
    if request.style == "anime":
        model_url = "https://api-inference.huggingface.co/models/cagliostrolab/animagine-xl-3.1"
        # 強化動漫風格提示詞
        payload["inputs"] = (
            f"masterpiece, best quality, anime screenshot, Studio Ghibli style, "
            f"2D illustration, delicious food, {request.prompt}"
        )
    else:
        model_url = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
        # 強化寫實風格提示詞
        payload["inputs"] = (
            f"{request.prompt}, professional food photography, 4k resolution, "
            f"highly detailed, photorealistic, appetizing, studio lighting"
        )

    print(
        f"INFO: 後端正在呼叫 HF 模型 ({request.style}) Generating image for: "
        f"{request.prompt[:30]}..."
    )

    try:
        # 呼叫 HF API
        response = requests.post(model_url, headers=headers, json=payload, timeout=60)

        if response.status_code != 200:
            print(f"ERROR: HF API 錯誤 ({response.status_code}): {response.text}")
            raise Exception("AI 生成圖片失敗")

        print("✅ 圖片生成成功，回傳給前端...")
        # 將二進位圖片資料傳回前端
        return StreamingResponse(io.BytesIO(response.content), media_type="image/jpeg")

    except Exception as e:
        print(f"ERROR: 後端圖片處理發生例外: {e}")
        # 若失敗，傳回 Unsplash 預設備用圖
        return RedirectResponse(
            url="https://images.unsplash.com/photo-1495195134817-aeb325a55b65?q=80&w=1024"
        )

