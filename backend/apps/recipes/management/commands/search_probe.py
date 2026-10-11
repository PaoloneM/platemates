from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from ai import get_chat_provider
from apps.assistant import search


class Command(BaseCommand):
    help = (
        "Show how recipe search reads requests and ranks the recipes a user can see: "
        "similarity, keyword match, score, and which are offered. Read only; uses the chat "
        "model (unless --plain) and the embedding model. For tuning the search.* settings."
    )

    def add_arguments(self, parser):
        parser.add_argument("requests", nargs="+", help="Requests, as a user would type them.")
        parser.add_argument("--user", required=True, help="Email of the user searching.")
        parser.add_argument("--language", default="Italian")
        parser.add_argument(
            "--plain", action="store_true", help="Skip the chat model: the request as typed."
        )
        parser.add_argument("--top", type=int, default=10)

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(email=options["user"]).first()
        if user is None:
            raise CommandError(f"No user {options['user']}.")
        chat = None if options["plain"] else get_chat_provider()
        for text in options["requests"]:
            request = (
                search.plain_request(text)
                if chat is None
                else search.understand(text, options["language"], chat)
            )
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{text}"))
            self.stdout.write(
                f"  query: {request.query}\n  keywords: {request.keywords}\n"
                f"  dishes: {request.dishes}\n  excluded: "
                f"{request.exclude_categories + request.exclude_ingredients}"
            )
            for s in search.rank(user, request)[: options["top"]]:
                mark = self.style.SUCCESS("offered") if s.kept else "       "
                keyword = "kw" if s.keyword else "  "
                self.stdout.write(
                    f"  {mark} {s.similarity:.2f} {keyword} {s.score:.2f}  {s.recipe.title}"
                )
