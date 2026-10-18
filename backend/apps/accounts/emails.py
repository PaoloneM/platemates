"""The emails the app sends (Keycloak sends its own: verification, password reset): HTML in
PlateMates' colours with a plain-text twin, in the recipient's language (Italian or English).
Texts live here, by message and language: the backend has no translation catalogue, and
they are few. Sending never raises: the caller learns whether it worked."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

log = logging.getLogger(__name__)


@dataclass
class Message:
    subject: str
    title: str
    paragraphs: list[str]
    button: str = ""
    path: str = ""  # where the button leads, on the public site
    quote: str = ""  # the sender's own words
    footer: tuple[str, ...] = ()


TEXTS = {
    "invitation": {
        "it": Message(
            subject="{inviter} ti invita nel team «{team}» su PlateMates",
            title="Un invito per te",
            paragraphs=[
                "{inviter} ({inviter_email}) ti invita a unirti al team «{team}» su PlateMates, "
                "l'app per il menu della settimana e la lista della spesa di chi mangia insieme.",
                "Accedi con Google o crea un account con questo indirizzo email ({email}): "
                "subito dopo potrai accettare l'invito.",
            ],
            button="Accetta l'invito",
            footer=(
                "L'invito vale fino al {expires} e solo per {email}.",
                "Se non conosci chi te lo manda, puoi ignorare questa email.",
            ),
        ),
        "en": Message(
            subject="{inviter} invites you to the team «{team}» on PlateMates",
            title="An invitation for you",
            paragraphs=[
                "{inviter} ({inviter_email}) invites you to join the team «{team}» on "
                "PlateMates, the app for the weekly menu and shopping list of people who eat "
                "together.",
                "Sign in with Google or create an account with this email address ({email}): "
                "right after, you can accept the invitation.",
            ],
            button="Accept the invitation",
            footer=(
                "The invitation is valid until {expires}, for {email} only.",
                "If you don't know who sent it, you can ignore this email.",
            ),
        ),
    },
    "access_request": {
        "it": Message(
            subject="{requester} chiede di entrare in un tuo team su PlateMates",
            title="Una richiesta di accesso",
            paragraphs=[
                "{requester} ({requester_email}) chiede di entrare in un team di cui sei "
                "proprietario.",
                "Puoi accettarla o rifiutarla dalla pagina Team: accettandola, entra subito.",
            ],
            button="Apri la pagina Team",
            path="/team#requests",
            footer=("Ricevi questa email perché sei proprietario di un team su PlateMates.",),
        ),
        "en": Message(
            subject="{requester} asks to join one of your teams on PlateMates",
            title="An access request",
            paragraphs=[
                "{requester} ({requester_email}) asks to join a team you own.",
                "You can accept or decline it from the Team page: once accepted, they are in.",
            ],
            button="Open the Team page",
            path="/team#requests",
            footer=("You get this email because you own a team on PlateMates.",),
        ),
    },
    "access_accepted": {
        "it": Message(
            subject="Sei nel team «{team}» su PlateMates",
            title="Benvenuto nel team «{team}»",
            paragraphs=["{owner} ha accettato la tua richiesta: ora fai parte del team «{team}»."],
            button="Apri PlateMates",
            path="/",
        ),
        "en": Message(
            subject="You are in the team «{team}» on PlateMates",
            title="Welcome to the team «{team}»",
            paragraphs=["{owner} accepted your request: you are now in the team «{team}»."],
            button="Open PlateMates",
            path="/",
        ),
    },
    "access_declined": {
        "it": Message(
            subject="La tua richiesta di accesso su PlateMates",
            title="Richiesta non accettata",
            paragraphs=[
                "La tua richiesta di entrare in un team non è stata accettata.",
                "Puoi chiedere a un altro proprietario, o chiedere un team tutto tuo.",
            ],
            button="Apri PlateMates",
            path="/",
        ),
        "en": Message(
            subject="Your access request on PlateMates",
            title="Request not accepted",
            paragraphs=[
                "Your request to join a team was not accepted.",
                "You can ask another owner, or ask for a team of your own.",
            ],
            button="Open PlateMates",
            path="/",
        ),
    },
    "team_created": {
        "it": Message(
            subject="Il tuo team «{team}» è pronto su PlateMates",
            title="Il tuo team è pronto",
            paragraphs=[
                "Abbiamo creato il team «{team}», e ne sei il proprietario.",
                "Dalla pagina Team puoi invitare le persone con cui mangi.",
            ],
            button="Apri PlateMates",
            path="/",
        ),
        "en": Message(
            subject="Your team «{team}» is ready on PlateMates",
            title="Your team is ready",
            paragraphs=[
                "We created the team «{team}», and you own it.",
                "From the Team page you can invite the people you eat with.",
            ],
            button="Open PlateMates",
            path="/",
        ),
    },
    "team_declined": {
        "it": Message(
            subject="La tua richiesta di un team su PlateMates",
            title="Richiesta non accettata",
            paragraphs=[
                "La tua richiesta di un nuovo team («{team}») non è stata accettata.",
                "Puoi chiedere a un proprietario di farti entrare nel suo.",
            ],
            button="Apri PlateMates",
            path="/",
        ),
        "en": Message(
            subject="Your request for a team on PlateMates",
            title="Request not accepted",
            paragraphs=[
                "Your request for a new team («{team}») was not accepted.",
                "You can ask an owner to let you into theirs.",
            ],
            button="Open PlateMates",
            path="/",
        ),
    },
}


def send(kind: str, to: str, language: str | None, *, url: str = "", **values) -> bool:
    """Send one of TEXTS to `to`, in `language` (Italian when unknown). `url` overrides the
    button's link. Returns whether the relay accepted it."""
    text = TEXTS[kind]["en" if language == "en" else "it"]
    fill = lambda s: s.format(**values)  # noqa: E731
    context = {
        "language": "en" if language == "en" else "it",
        "app_url": settings.APP_URL,
        "subject": fill(text.subject),
        "title": fill(text.title),
        "paragraphs": [fill(p) for p in text.paragraphs],
        "quote": values.get("message", ""),
        "button": text.button,
        "button_url": url or (f"{settings.APP_URL}{text.path}" if text.path else ""),
        "footer": [fill(f) for f in text.footer],
    }
    plain = "\n\n".join(
        [
            context["title"],
            *context["paragraphs"],
            context["quote"],
            f"{context['button']}: {context['button_url']}" if context["button_url"] else "",
            *context["footer"],
        ]
    ).strip()
    message = EmailMultiAlternatives(context["subject"], plain, settings.DEFAULT_FROM_EMAIL, [to])
    message.attach_alternative(render_to_string("emails/base.html", context), "text/html")
    try:
        message.send()
    except Exception:
        log.exception("email %s to a recipient not sent", kind)
        return False
    return True
