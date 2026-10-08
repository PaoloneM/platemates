from rest_framework import serializers

from apps.recipes.models import Course, Recipe

from .calendar import NewDish
from .models import PLANNED_MEALS, Meal, Member, Membership, Preference, RecipeBookEntry, Team

MAX_PEOPLE = 50


class MemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = Member
        fields = ["id", "team", "name", "birth_year"]


class PreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Preference
        fields = ["id", "team", "member", "kind", "ingredient", "cuisine", "note"]


class TeamSerializer(serializers.ModelSerializer):
    members = MemberSerializer(many=True, read_only=True)
    preferences = PreferenceSerializer(many=True, read_only=True)
    # The requesting user's role: the interface shows owners the editing controls.
    my_role = serializers.SerializerMethodField()

    def get_my_role(self, team) -> str | None:
        membership = team.memberships.filter(user=self.context["request"].user).first()
        return membership.role if membership else None

    def validate_name(self, name: str) -> str:
        name = " ".join(name.split())
        if not name:
            raise serializers.ValidationError("A team needs a name.")
        return name

    def validate_typical_week(self, value):
        """Seven days, Monday first: `active`, and 0 to MAX_PEOPLE people for each meal."""
        if not isinstance(value, list) or len(value) != 7:
            raise serializers.ValidationError("Expected seven days, Monday first.")
        cleaned = []
        for day in value:
            if not isinstance(day, dict) or set(day) - {"active", *Meal.values}:
                raise serializers.ValidationError(f"Each day: active, {', '.join(Meal.values)}.")
            if not isinstance(day.get("active", True), bool):
                raise serializers.ValidationError("active: true or false.")
            counts = {}
            for meal in Meal.values:
                count = day.get(meal, 0)
                if type(count) is not int or not 0 <= count <= MAX_PEOPLE:
                    raise serializers.ValidationError(f"{meal}: 0 to {MAX_PEOPLE} people.")
                counts[meal] = count
            cleaned.append({"active": day.get("active", True), **counts})
        return cleaned

    class Meta:
        model = Team
        fields = [
            "id",
            "name",
            "tools",
            "typical_week",
            "max_weekday_minutes",
            "notes",
            "members",
            "preferences",
            "my_role",
        ]


class RecipeSummarySerializer(serializers.Serializer):
    """What the recipe book list shows of each recipe."""

    id = serializers.IntegerField()
    title = serializers.CharField()
    course = serializers.CharField()
    cuisine_name = serializers.CharField(source="cuisine.name", default=None)
    servings = serializers.IntegerField()
    total_minutes = serializers.IntegerField()
    season_months = serializers.ListField(child=serializers.IntegerField())
    # Both seasonality levels combined (ingredients and climate): what "in season" means.
    # Empty = suitable all year.
    suitable_months = serializers.SerializerMethodField()
    visibility = serializers.CharField()

    def get_suitable_months(self, recipe) -> list[int]:
        months = recipe.suitable_months()
        return [] if len(months) == 12 else sorted(months)


class RecipeBookEntrySerializer(serializers.ModelSerializer):
    recipe_summary = RecipeSummarySerializer(source="recipe", read_only=True)

    class Meta:
        model = RecipeBookEntry
        fields = [
            "id",
            "team",
            "recipe",
            "recipe_summary",
            "status",
            "rating",
            "notes",
            "added_at",
        ]


class MembershipSerializer(serializers.ModelSerializer):
    """A user with access to the team, and their role."""

    name = serializers.SerializerMethodField()
    email = serializers.EmailField(source="user.email", read_only=True)
    is_me = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = ["id", "team", "name", "email", "role", "is_me"]
        read_only_fields = ["team"]

    def get_name(self, membership) -> str:
        user = membership.user
        return (
            " ".join(filter(None, [user.first_name, user.last_name])) or user.email or user.username
        )

    def get_is_me(self, membership) -> bool:
        return membership.user_id == self.context["request"].user.pk


class CalendarDishSerializer(serializers.Serializer):
    recipe = serializers.IntegerField(allow_null=True)
    title = serializers.CharField()
    course = serializers.CharField()
    proposed = serializers.BooleanField()
    note = serializers.CharField()


class CalendarDaySerializer(serializers.Serializer):
    """A date of the team calendar, as `apps.teams.calendar.Day`."""

    date = serializers.DateField()
    active = serializers.BooleanField()
    usual = serializers.DictField(child=serializers.IntegerField())
    people = serializers.DictField(child=serializers.IntegerField())
    overridden = serializers.ListField(child=serializers.CharField())
    note = serializers.CharField()
    dishes = serializers.DictField(child=CalendarDishSerializer(many=True))
    proposed_people = serializers.DictField(child=serializers.IntegerField())
    people_notes = serializers.DictField(child=serializers.CharField())


class CalendarDayInputSerializer(serializers.Serializer):
    """What an owner changes on a date; every part is optional and the rest is kept.

    `people`: meal -> count. `note`: replaces the note. `dishes`: planned meal -> dishes, in
    order, replacing that meal's dishes (`[]` clears it); a dish is a recipe id, or
    `{"title": ..., "course": ...}` for a dish without a recipe.
    """

    people = serializers.DictField(child=serializers.IntegerField(), required=False)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True)
    dishes = serializers.DictField(child=serializers.ListField(), required=False)

    def validate_people(self, value):
        if set(value) - set(Meal.values):
            raise serializers.ValidationError(f"Meals are {', '.join(Meal.values)}.")
        if any(not 0 <= count <= MAX_PEOPLE for count in value.values()):
            raise serializers.ValidationError(f"0 to {MAX_PEOPLE} people.")
        return value

    def validate_note(self, value: str) -> str:
        return " ".join(value.split())

    def validate_dishes(self, value):
        """Recipe ids become recipes the user can see, titles `NewDish`es; only planned meals
        have dishes."""
        if set(value) - set(PLANNED_MEALS):
            raise serializers.ValidationError(f"Dishes go to {', '.join(PLANNED_MEALS)}.")
        wanted = set()
        for items in value.values():
            for item in items:
                if type(item) is int:
                    wanted.add(item)
                elif not (isinstance(item, dict) and isinstance(item.get("title"), str)):
                    raise serializers.ValidationError("A dish is a recipe id or {title, course}.")
        visible = Recipe.objects.visible_to(self.context["request"].user).in_bulk(wanted)
        if missing := wanted - set(visible):
            raise serializers.ValidationError(f"Unknown recipes: {sorted(missing)}.")
        return {
            meal: [self._dish(item, visible) for item in items] for meal, items in value.items()
        }

    @staticmethod
    def _dish(item, visible):
        if type(item) is int:
            return visible[item]
        title = " ".join(item["title"].split())[:200]
        course = item.get("course") or ""
        if not title:
            raise serializers.ValidationError("A dish needs a title.")
        if course not in {"", *Course.values}:
            raise serializers.ValidationError(f"Courses are {', '.join(Course.values)}.")
        return NewDish(title=title, course=course)
