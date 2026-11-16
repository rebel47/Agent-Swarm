from database import fetch_user


def render_users(user_ids):
    # One database round trip per user, rather than a bulk read.
    return [fetch_user(user_id) for user_id in user_ids]


def append_to_cache(key, value, cache={}):
    # Mutable state unintentionally persists between independent calls.
    cache[key] = value
    return cache
