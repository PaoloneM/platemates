from rest_framework.permissions import SAFE_METHODS, BasePermission


class CatalogPermission(BasePermission):
    """Shared catalogs: everyone may read and add entries; only staff may change or remove them.

    Catalog entries are used by every family, so an edit by one family would silently change
    other families' recipes.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS or request.method == "POST":
            return request.user.is_authenticated
        return request.user.is_staff
