from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def require_perm(permission: str):
    """
    Allow access if the user is a superuser or has the given permission codename
    (full string: e.g. masters.view_client).
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if request.user.is_superuser or request.user.has_perm(permission):
                return view_func(request, *args, **kwargs)
            raise PermissionDenied

        return _wrapped

    return decorator
