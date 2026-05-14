"""
routers/meals.py — CRUD for meal logging + daily aggregation.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.deps import CurrentUser, DBSession
from backend.models import DailyLog, Meal, User
from backend.schemas import (
    DailyLogOut,
    MealCreate,
    MealHistoryOut,
    MealOut,
    MealUpdate,
    TodayOut,
)
from backend.services.gamification_service import gamification_service

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_today(user: User) -> date:
    """Return today's date in the user's timezone (best-effort)."""
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(user.timezone or "UTC")
        return datetime.now(tz).date()
    except Exception:
        return datetime.now(timezone.utc).date()


async def _get_or_create_daily_log(db: AsyncSession, user_id: int, log_date: date) -> DailyLog:
    result = await db.execute(
        select(DailyLog).where(DailyLog.user_id == user_id, DailyLog.log_date == log_date)
    )
    log = result.scalar_one_or_none()
    if log is None:
        log = DailyLog(user_id=user_id, log_date=log_date)
        db.add(log)
        await db.flush()
    return log


async def _recompute_daily_log(db: AsyncSession, user: User, log: DailyLog) -> None:
    """Recompute aggregated totals for a DailyLog from its meals."""
    result = await db.execute(
        select(Meal).where(
            Meal.user_id == user.id,
            func.date(Meal.logged_at) == log.log_date,
        )
    )
    meals = result.scalars().all()

    log.meal_count      = len(meals)
    log.total_calories  = sum((m.calories  or Decimal(0)) for m in meals)
    log.total_protein_g = sum((m.protein_g or Decimal(0)) for m in meals)
    log.total_carbs_g   = sum((m.carbs_g   or Decimal(0)) for m in meals)
    log.total_fat_g     = sum((m.fat_g     or Decimal(0)) for m in meals)

    # Check goal attainment
    if user.calorie_goal and log.total_calories:
        log.calorie_goal_met = log.total_calories <= user.calorie_goal
    if user.protein_goal and log.total_protein_g:
        log.protein_goal_met = log.total_protein_g >= user.protein_goal
    if user.carbs_goal and log.total_carbs_g:
        log.carbs_goal_met = log.total_carbs_g <= user.carbs_goal
    if user.fat_goal and log.total_fat_g:
        log.fat_goal_met = log.total_fat_g <= user.fat_goal

    log.is_perfect_macro_day = bool(
        log.calorie_goal_met and log.protein_goal_met
        and log.carbs_goal_met and log.fat_goal_met
    )


# ---------------------------------------------------------------------------
# POST /meals
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=MealOut,
    status_code=status.HTTP_201_CREATED,
    summary="Log a new meal",
)
async def create_meal(
    body:         MealCreate,
    current_user: CurrentUser,
    db:           DBSession,
) -> MealOut:
    logged_at = body.logged_at or datetime.now(timezone.utc)
    meal = Meal(
        user_id          = current_user.id,
        food_name        = body.food_name,
        description      = body.description,
        meal_type        = body.meal_type,
        serving_g        = body.serving_g,
        calories         = body.calories,
        protein_g        = body.protein_g,
        carbs_g          = body.carbs_g,
        fat_g            = body.fat_g,
        fiber_g          = body.fiber_g,
        sugar_g          = body.sugar_g,
        photo_url        = body.photo_url,
        confidence_score = body.confidence_score,
        logged_at        = logged_at,
    )
    db.add(meal)
    await db.flush()

    # Update daily log
    log = await _get_or_create_daily_log(db, current_user.id, logged_at.date())
    await _recompute_daily_log(db, current_user, log)

    # Award XP / achievements
    await gamification_service.process_meal_logged(db, current_user, meal, log)

    return MealOut.model_validate(meal)


# ---------------------------------------------------------------------------
# GET /meals/today
# ---------------------------------------------------------------------------

@router.get(
    "/today",
    response_model=TodayOut,
    summary="Return today's meals and aggregated log",
)
async def get_today(
    current_user: CurrentUser,
    db:           DBSession,
) -> TodayOut:
    today = _user_today(current_user)

    meals_result = await db.execute(
        select(Meal)
        .where(Meal.user_id == current_user.id, func.date(Meal.logged_at) == today)
        .order_by(Meal.logged_at)
    )
    meals = meals_result.scalars().all()

    log_result = await db.execute(
        select(DailyLog).where(
            DailyLog.user_id == current_user.id,
            DailyLog.log_date == today,
        )
    )
    log = log_result.scalar_one_or_none()

    return TodayOut(
        meals     = [MealOut.model_validate(m) for m in meals],
        daily_log = DailyLogOut.model_validate(log) if log else None,
    )


# ---------------------------------------------------------------------------
# GET /meals/history
# ---------------------------------------------------------------------------

@router.get(
    "/history",
    response_model=MealHistoryOut,
    summary="Return daily log history",
)
async def get_history(
    current_user: CurrentUser,
    db:           DBSession,
    days:         int = Query(default=7, ge=1, le=90),
) -> MealHistoryOut:
    today    = _user_today(current_user)
    from_date = today - timedelta(days=days - 1)

    result = await db.execute(
        select(DailyLog)
        .where(
            DailyLog.user_id  == current_user.id,
            DailyLog.log_date >= from_date,
            DailyLog.log_date <= today,
        )
        .order_by(DailyLog.log_date.desc())
    )
    logs = result.scalars().all()
    return MealHistoryOut(days=[DailyLogOut.model_validate(l) for l in logs])


# ---------------------------------------------------------------------------
# DELETE /meals/{id}
# ---------------------------------------------------------------------------

@router.delete(
    "/{meal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a meal by ID",
)
async def delete_meal(
    meal_id:      int,
    current_user: CurrentUser,
    db:           DBSession,
) -> None:
    result = await db.execute(
        select(Meal).where(Meal.id == meal_id, Meal.user_id == current_user.id)
    )
    meal = result.scalar_one_or_none()
    if meal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meal not found")

    log_date = meal.logged_at.date()
    await db.delete(meal)
    await db.flush()

    # Recompute daily log after deletion
    log = await _get_or_create_daily_log(db, current_user.id, log_date)
    await _recompute_daily_log(db, current_user, log)


# ---------------------------------------------------------------------------
# PUT /meals/{id}
# ---------------------------------------------------------------------------

@router.put(
    "/{meal_id}",
    response_model=MealOut,
    summary="Update a meal",
)
async def update_meal(
    meal_id:      int,
    body:         MealUpdate,
    current_user: CurrentUser,
    db:           DBSession,
) -> MealOut:
    result = await db.execute(
        select(Meal).where(Meal.id == meal_id, Meal.user_id == current_user.id)
    )
    meal = result.scalar_one_or_none()
    if meal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meal not found")

    old_log_date = meal.logged_at.date()

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(meal, field, value)

    await db.flush()

    # Recompute old date if logged_at changed
    if body.logged_at and body.logged_at.date() != old_log_date:
        old_log = await _get_or_create_daily_log(db, current_user.id, old_log_date)
        await _recompute_daily_log(db, current_user, old_log)

    new_log = await _get_or_create_daily_log(db, current_user.id, meal.logged_at.date())
    await _recompute_daily_log(db, current_user, new_log)

    return MealOut.model_validate(meal)
