from rest_framework.permissions import SAFE_METHODS, BasePermission


class CatalogPermission(BasePermission):
    """Shared catalogs: everyone may read and add entries; only staff may change or remove them.

    Catalog entries are used by every team, so an edit by one team would silently change
    other teams' recipes.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS or request.method == "POST":
            return request.user.is_authenticated
        return request.user.is_staff


class IsAppAdmin(BasePermission):
    """Application administrators: users holding Keycloak's `admin` realm role."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user.is_authenticated and getattr(getattr(user, "profile", None), "is_admin", False)
        )


class StaffWritesPermission(BasePermission):
    """Shared settings every user reads and only staff change."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return request.user.is_authenticated
        return request.user.is_staff
