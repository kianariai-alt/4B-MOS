from backend.app.models.user import User


def actor_data(
    actor: User | None,
) -> dict:
    if actor is None:
        return {
            "actor_user_id": None,
            "actor_username": None,
            "actor_display_name": None,
            "actor_role": None,
        }

    return {
        "actor_user_id": actor.id,
        "actor_username": actor.username,
        "actor_display_name": actor.display_name,
        "actor_role": actor.role,
    }