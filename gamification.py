"""
routers/gamification.py — XP, achievements, leaderboard, challenges, claim.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from backend.deps import CurrentUser, DBSession
from backend.models import (
    Achievement,
    Challenge,
    ChallengeStatus,
    Leaderboard,
    User,
    UserAchievement,
    UserChallenge,
    UserStats,
    LEVEL_THRESHOLDS,
)
from backend.services.gamification_service import XPEvent
from backend.schemas import (
    AchievementOut,
    ChallengeOut,
    ClaimOut,
    ClaimRequest,
    LeaderboardEntry,
    LeaderboardOut,
    UserStatsOut,
)
from backend.services.gamification_service import (
    gamification_service,
    xp_to_next_level as xp_to_next,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /gamification/stats
# ---------------------------------------------------------------------------

@router.get(
    "/stats",
    response_model=UserStatsOut,
    summary="Return XP, level, and streak info for the current user",
)
async def get_stats(
    current_user: CurrentUser,
    db:           DBSession,
) -> UserStatsOut:
    result = await db.execute(
        select(UserStats).where(UserStats.user_id == current_user.id)
    )
    stats = result.scalar_one_or_none()

    if stats is None:
        # Bootstrap if missing (shouldn't happen after auth)
        stats = UserStats(user_id=current_user.id)
        db.add(stats)
        await db.flush()

    return UserStatsOut(
        total_xp           = stats.total_xp,
        current_level      = stats.current_level,
        current_streak     = stats.current_streak,
        longest_streak     = stats.longest_streak,
        total_meals_logged = stats.total_meals_logged,
        xp_to_next_level   = xp_to_next(stats.total_xp, stats.current_level),
    )


# ---------------------------------------------------------------------------
# GET /gamification/achievements
# ---------------------------------------------------------------------------

@router.get(
    "/achievements",
    response_model=list[AchievementOut],
    summary="Return all achievements with earned status",
)
async def get_achievements(
    current_user: CurrentUser,
    db:           DBSession,
) -> list[AchievementOut]:
    # All active achievements
    ach_result = await db.execute(
        select(Achievement).where(Achievement.is_active == True).order_by(Achievement.id)
    )
    achievements = ach_result.scalars().all()

    # User's earned achievements
    ua_result = await db.execute(
        select(UserAchievement).where(UserAchievement.user_id == current_user.id)
    )
    user_achievements = {ua.achievement_id: ua for ua in ua_result.scalars().all()}

    out: list[AchievementOut] = []
    for ach in achievements:
        ua = user_achievements.get(ach.id)
        out.append(
            AchievementOut(
                id          = ach.id,
                code        = ach.code,
                title       = ach.title,
                description = ach.description,
                icon_url    = ach.icon_url,
                xp_reward   = ach.xp_reward,
                earned      = ua is not None,
                earned_at   = ua.earned_at if ua else None,
                notified    = ua.notified if ua else False,
            )
        )
    return out


# ---------------------------------------------------------------------------
# GET /gamification/leaderboard
# ---------------------------------------------------------------------------

@router.get(
    "/leaderboard",
    response_model=LeaderboardOut,
    summary="Weekly XP leaderboard",
)
async def get_leaderboard(
    current_user: CurrentUser,
    db:           DBSession,
) -> LeaderboardOut:
    # Current ISO week key, e.g. "2024-W22"
    today     = datetime.now(timezone.utc).date()
    period_key = f"{today.isocalendar().year}-W{today.isocalendar().week:02d}"

    result = await db.execute(
        select(Leaderboard, User)
        .join(User, Leaderboard.user_id == User.id)
        .where(Leaderboard.period == "weekly", Leaderboard.period_key == period_key)
        .order_by(Leaderboard.xp_earned.desc())
        .limit(100)
    )
    rows = result.all()

    entries: list[LeaderboardEntry] = []
    my_rank: int | None = None

    for rank, (lb, user) in enumerate(rows, start=1):
        is_me = user.id == current_user.id
        if is_me:
            my_rank = rank
        entries.append(
            LeaderboardEntry(
                rank              = rank,
                user_id           = user.id,
                display_name      = user.display_name,
                telegram_username = user.telegram_username,
                telegram_photo    = user.telegram_photo,
                xp_earned         = lb.xp_earned,
                meals_logged      = lb.meals_logged,
                streak            = lb.streak,
                is_me             = is_me,
            )
        )

    return LeaderboardOut(
        period     = "weekly",
        period_key = period_key,
        entries    = entries,
        my_rank    = my_rank,
    )


# ---------------------------------------------------------------------------
# GET /gamification/challenges
# ---------------------------------------------------------------------------

@router.get(
    "/challenges",
    response_model=list[ChallengeOut],
    summary="Return today's active daily challenges with progress",
)
async def get_challenges(
    current_user: CurrentUser,
    db:           DBSession,
) -> list[ChallengeOut]:
    today = datetime.now(timezone.utc).date()

    # Fetch challenge catalogue
    ch_result = await db.execute(
        select(Challenge).where(Challenge.is_active == True, Challenge.is_daily == True)
    )
    challenges = ch_result.scalars().all()

    # Fetch (or bootstrap) user's challenge instances for today
    uc_result = await db.execute(
        select(UserChallenge).where(
            UserChallenge.user_id       == current_user.id,
            UserChallenge.challenge_date == today,
        )
    )
    user_challenges = {uc.challenge_id: uc for uc in uc_result.scalars().all()}

    # Bootstrap any missing instances
    for ch in challenges:
        if ch.id not in user_challenges:
            uc = UserChallenge(
                user_id       = current_user.id,
                challenge_id  = ch.id,
                challenge_date = today,
                status        = ChallengeStatus.active,
                progress      = Decimal(0),
            )
            db.add(uc)
            await db.flush()
            user_challenges[ch.id] = uc

    out: list[ChallengeOut] = []
    for ch in challenges:
        uc = user_challenges[ch.id]
        target = ch.target_value or Decimal(1)
        pct = float(min(uc.progress / target * 100, 100)) if target else 0.0

        out.append(
            ChallengeOut(
                id             = ch.id,
                code           = ch.code,
                title          = ch.title,
                description    = ch.description,
                challenge_type = ch.challenge_type.value,
                target_value   = ch.target_value,
                target_unit    = ch.target_unit,
                xp_reward      = ch.xp_reward,
                progress       = uc.progress,
                status         = uc.status.value,
                pct_complete   = round(pct, 1),
            )
        )
    return out


# ---------------------------------------------------------------------------
# POST /gamification/claim
# ---------------------------------------------------------------------------

@router.post(
    "/claim",
    response_model=ClaimOut,
    summary="Claim XP reward for a completed achievement",
)
async def claim_achievement(
    body:         ClaimRequest,
    current_user: CurrentUser,
    db:           DBSession,
) -> ClaimOut:
    # Find user achievement
    ua_result = await db.execute(
        select(UserAchievement).where(
            UserAchievement.user_id        == current_user.id,
            UserAchievement.achievement_id == body.achievement_id,
        )
    )
    ua = ua_result.scalar_one_or_none()
    if ua is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Achievement not earned yet")

    if ua.notified:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="XP already claimed for this achievement")

    # Fetch achievement to know the reward
    ach_result = await db.execute(
        select(Achievement).where(Achievement.id == body.achievement_id)
    )
    achievement = ach_result.scalar_one_or_none()
    if achievement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Achievement not found")

    # Fetch stats
    stats_result = await db.execute(
        select(UserStats).where(UserStats.user_id == current_user.id)
    )
    stats = stats_result.scalar_one_or_none()
    if stats is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Stats not initialised")

    old_level = stats.current_level
    xp_result  = await gamification_service.award_xp(db, current_user, XPEvent.ACHIEVEMENT_EARNED, amount=achievement.xp_reward)
    total_xp   = xp_result.total_xp
    leveled_up = xp_result.leveled_up

    # Mark as notified/claimed
    ua.notified = True

    return ClaimOut(
        xp_awarded   = achievement.xp_reward,
        new_total_xp = total_xp,
        new_level    = stats.current_level,
        level_up     = leveled_up,
    )
