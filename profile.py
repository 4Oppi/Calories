"""
routers/profile.py — GET/PUT /profile, POST /profile/calculate-tdee
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from backend.deps import CurrentUser, DBSession
from backend.schemas import ProfileUpdate, TDEEOut, TDEERequest, UserOut

router = APIRouter()

# ---------------------------------------------------------------------------
# Inline TDEE calculator (Mifflin-St Jeor)
# ---------------------------------------------------------------------------

_ACTIVITY_FACTORS = {
    "sedentary":   1.200,
    "light":       1.375,
    "moderate":    1.550,
    "active":      1.725,
    "very_active": 1.900,
}

_GOAL_ADJUSTMENTS = {"lose": -500, "maintain": 0, "gain": 300}


def calculate_tdee(
    weight_kg: float,
    height_cm: float,
    age:       int,
    sex:       str,
    activity:  str,
    goal:      str,
) -> dict:
    """Mifflin-St Jeor BMR → TDEE → recommended macros."""
    if sex == "male":
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    else:
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161

    tdee             = int(bmr * _ACTIVITY_FACTORS[activity])
    recommended_cal  = max(1200, tdee + _GOAL_ADJUSTMENTS[goal])

    # Macro split: 30 % protein · 40 % carbs · 30 % fat
    protein_g = int(recommended_cal * 0.30 / 4)
    carbs_g   = int(recommended_cal * 0.40 / 4)
    fat_g     = int(recommended_cal * 0.30 / 9)

    return {
        "bmr":             int(bmr),
        "tdee":            tdee,
        "recommended_cal": recommended_cal,
        "protein_g":       protein_g,
        "carbs_g":         carbs_g,
        "fat_g":           fat_g,
    }


# ---------------------------------------------------------------------------
# GET /profile
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=UserOut,
    summary="Return the current user's full profile",
)
async def get_profile(current_user: CurrentUser) -> UserOut:
    return UserOut.model_validate(current_user)


# ---------------------------------------------------------------------------
# PUT /profile
# ---------------------------------------------------------------------------

@router.put(
    "",
    response_model=UserOut,
    summary="Update profile fields and/or calorie/macro goals",
)
async def update_profile(
    body:         ProfileUpdate,
    current_user: CurrentUser,
    db:           DBSession,
) -> UserOut:
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    for field, value in updates.items():
        setattr(current_user, field, value)

    return UserOut.model_validate(current_user)


# ---------------------------------------------------------------------------
# POST /profile/calculate-tdee
# ---------------------------------------------------------------------------

@router.post(
    "/calculate-tdee",
    response_model=TDEEOut,
    summary="Calculate TDEE and save recommended calorie/macro goals",
)
async def calculate_and_save_tdee(
    body:         TDEERequest,
    current_user: CurrentUser,
    db:           DBSession,
) -> TDEEOut:
    result = calculate_tdee(
        weight_kg = body.weight_kg,
        height_cm = body.height_cm,
        age       = body.age,
        sex       = body.sex,
        activity  = body.activity,
        goal      = body.goal,
    )

    # Persist goals
    current_user.calorie_goal = result["recommended_cal"]
    current_user.protein_goal = result["protein_g"]
    current_user.carbs_goal   = result["carbs_g"]
    current_user.fat_goal     = result["fat_g"]

    return TDEEOut(**result)
