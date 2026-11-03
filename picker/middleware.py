import re
import uuid

VOTER_COOKIE = "voter"
VOTER_COOKIE_AGE = 2 * 365 * 24 * 3600
_VALID_ID = re.compile(r"^[0-9a-f]{32}$")


class VoterMiddleware:
    """Give every browser a stable anonymous id in ``request.voter_id``.

    There are no accounts, so this cookie is what "one vote per person" means.
    The cookie is set after the view runs, so redirects and 204s carry it too.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        cookie = request.COOKIES.get(VOTER_COOKIE, "")
        is_new = not _VALID_ID.match(cookie)
        request.voter_id = uuid.uuid4().hex if is_new else cookie
        response = self.get_response(request)
        if is_new:
            response.set_cookie(
                VOTER_COOKIE, request.voter_id,
                max_age=VOTER_COOKIE_AGE, httponly=True, samesite="Lax",
            )
        return response
