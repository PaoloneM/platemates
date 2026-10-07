"""Seed the catalog with common ingredients, so the first recipes find most of what they need.

Italian names (the language of the first deployment), Italian seasonality, plural forms as
aliases. Idempotent and never destructive: an entry is skipped when an ingredient already exists
under its name or one of its aliases, and existing ingredients are left untouched. Everything
stays editable from the app's management section.

Preserved forms whose season differs from the fresh product are distinct ingredients ("pomodoro
pelato", "passata di pomodoro" are all year, "pomodoro" is summer).
"""

from django.db import migrations

ALL = []  # available all year
WINTER = [11, 12, 1, 2]
COLD = [10, 11, 12, 1, 2, 3]
SUMMER = [6, 7, 8, 9]

# (name, category, default unit, season months, aliases)
INGREDIENTS = [
    # -- vegetables
    ("aglio", "vegetable", "pc", ALL, ["spicchio d'aglio"]),
    ("asparago", "vegetable", "g", [3, 4, 5, 6], ["asparagi"]),
    ("barbabietola", "vegetable", "g", [6, 7, 8, 9, 10, 11], ["barbabietole"]),
    ("bietola", "vegetable", "g", [3, 4, 5, 6, 9, 10, 11], ["bietole", "erbette"]),
    ("broccolo", "vegetable", "g", COLD, ["broccoli"]),
    ("carciofo", "vegetable", "pc", [11, 12, 1, 2, 3, 4], ["carciofi"]),
    ("carota", "vegetable", "g", ALL, ["carote"]),
    ("cavolfiore", "vegetable", "g", COLD, ["cavolfiori"]),
    ("cavolo cappuccio", "vegetable", "g", COLD, ["cavolo"]),
    ("cavolo nero", "vegetable", "g", WINTER, []),
    ("cavolino di bruxelles", "vegetable", "g", WINTER, ["cavolini di bruxelles"]),
    ("cetriolo", "vegetable", "pc", SUMMER, ["cetrioli"]),
    ("cicoria", "vegetable", "g", COLD, []),
    ("cima di rapa", "vegetable", "g", WINTER, ["cime di rapa", "broccoletti"]),
    ("cipolla", "vegetable", "pc", ALL, ["cipolle", "cipolla bianca", "cipolla dorata"]),
    ("cipollotto", "vegetable", "pc", [4, 5, 6, 7, 8, 9], ["cipollotti"]),
    ("fagiolino", "vegetable", "g", SUMMER, ["fagiolini"]),
    ("fava", "vegetable", "g", [4, 5, 6], ["fave"]),
    ("finocchio", "vegetable", "pc", [10, 11, 12, 1, 2, 3, 4], ["finocchi"]),
    ("fungo champignon", "vegetable", "g", ALL, ["champignon", "funghi champignon"]),
    ("fungo porcino", "vegetable", "g", [8, 9, 10, 11], ["porcini", "funghi porcini"]),
    ("lattuga", "vegetable", "g", [4, 5, 6, 7, 8, 9, 10], ["insalata"]),
    ("mais", "vegetable", "g", [7, 8, 9], ["mais dolce"]),
    ("melanzana", "vegetable", "pc", SUMMER, ["melanzane"]),
    ("patata", "vegetable", "g", ALL, ["patate"]),
    ("peperone", "vegetable", "pc", SUMMER, ["peperoni"]),
    ("pisello", "vegetable", "g", [4, 5, 6], ["piselli"]),
    ("pomodoro", "vegetable", "g", SUMMER, ["pomodori"]),
    ("pomodorino", "vegetable", "g", [5, 6, 7, 8, 9, 10], ["pomodorini", "pomodorini ciliegini"]),
    ("porro", "vegetable", "g", [9, 10, 11, 12, 1, 2, 3, 4], ["porri"]),
    ("radicchio", "vegetable", "g", [11, 12, 1, 2, 3], []),
    ("rucola", "vegetable", "g", [4, 5, 6, 7, 8, 9, 10], []),
    ("scalogno", "vegetable", "pc", ALL, ["scalogni"]),
    ("sedano", "vegetable", "g", ALL, ["costa di sedano"]),
    ("spinacio", "vegetable", "g", [10, 11, 12, 1, 2, 3, 4], ["spinaci"]),
    ("verza", "vegetable", "g", [10, 11, 12, 1, 2], []),
    ("zucca", "vegetable", "g", [9, 10, 11, 12, 1], []),
    ("zucchina", "vegetable", "g", [5, 6, 7, 8, 9], ["zucchine"]),
    ("pomodoro pelato", "condiment", "g", ALL, ["pomodori pelati", "pelati"]),
    ("passata di pomodoro", "condiment", "ml", ALL, ["passata"]),
    ("concentrato di pomodoro", "condiment", "g", ALL, []),
    ("pisello surgelato", "vegetable", "g", ALL, ["piselli surgelati"]),
    # -- fruit
    ("albicocca", "fruit", "pc", [6, 7], ["albicocche"]),
    ("anguria", "fruit", "g", [6, 7, 8], ["cocomero"]),
    ("arancia", "fruit", "pc", [11, 12, 1, 2, 3, 4], ["arance"]),
    ("banana", "fruit", "pc", ALL, ["banane"]),
    ("cachi", "fruit", "pc", [10, 11, 12], ["kaki"]),
    ("castagna", "fruit", "g", [10, 11, 12], ["castagne"]),
    ("ciliegia", "fruit", "g", [5, 6, 7], ["ciliegie"]),
    ("fico", "fruit", "pc", [7, 8, 9], ["fichi"]),
    ("fragola", "fruit", "g", [4, 5, 6], ["fragole"]),
    ("kiwi", "fruit", "pc", [11, 12, 1, 2, 3], []),
    ("limone", "fruit", "pc", ALL, ["limoni"]),
    ("mandarino", "fruit", "pc", [11, 12, 1, 2], ["mandarini", "clementina"]),
    ("mela", "fruit", "pc", [8, 9, 10, 11, 12, 1, 2, 3], ["mele"]),
    ("melagrana", "fruit", "pc", [10, 11, 12], ["melograno"]),
    ("melone", "fruit", "g", [6, 7, 8, 9], ["meloni"]),
    ("mirtillo", "fruit", "g", [6, 7, 8], ["mirtilli"]),
    ("pera", "fruit", "pc", [8, 9, 10, 11, 12, 1], ["pere"]),
    ("pesca", "fruit", "pc", [6, 7, 8, 9], ["pesche"]),
    ("prugna", "fruit", "pc", [7, 8, 9], ["prugne", "susina"]),
    ("uva", "fruit", "g", [8, 9, 10], []),
    ("uvetta", "fruit", "g", ALL, ["uva sultanina", "uva passa"]),
    ("oliva", "fruit", "g", ALL, ["olive"]),
    # -- legumes (dried or canned: all year)
    ("cece", "legume", "g", ALL, ["ceci"]),
    ("fagiolo borlotto", "legume", "g", ALL, ["fagioli borlotti", "borlotti"]),
    ("fagiolo cannellino", "legume", "g", ALL, ["fagioli cannellini", "cannellini"]),
    ("lenticchia", "legume", "g", ALL, ["lenticchie", "lenticchie secche"]),
    ("piselli secchi", "legume", "g", ALL, []),
    # -- cereals, pasta, bread
    ("couscous", "cereal", "g", ALL, ["cous cous"]),
    ("ditalini", "cereal", "g", ALL, ["ditalino"]),
    ("farina 00", "cereal", "g", ALL, ["farina"]),
    ("farina integrale", "cereal", "g", ALL, []),
    ("farina di mais", "cereal", "g", ALL, ["polenta"]),
    ("farro", "cereal", "g", ALL, []),
    ("fusilli", "cereal", "g", ALL, []),
    ("gnocchi di patate", "cereal", "g", ALL, ["gnocchi"]),
    ("orzo", "cereal", "g", ALL, ["orzo perlato"]),
    ("pane", "cereal", "g", ALL, []),
    ("pangrattato", "cereal", "g", ALL, ["pan grattato"]),
    ("pasta brisée", "cereal", "g", ALL, ["brisée"]),
    ("pasta sfoglia", "cereal", "g", ALL, []),
    ("penne", "cereal", "g", ALL, []),
    ("riso", "cereal", "g", ALL, ["riso carnaroli", "riso arborio"]),
    ("rigatoni", "cereal", "g", ALL, []),
    ("semola di grano duro", "cereal", "g", ALL, ["semola"]),
    ("sfoglia per lasagne", "cereal", "g", ALL, ["lasagne"]),
    ("spaghetti", "cereal", "g", ALL, []),
    ("tagliatelle", "cereal", "g", ALL, []),
    ("fiocchi d'avena", "cereal", "g", ALL, ["avena"]),
    # -- meat
    ("bresaola", "cured_meat", "g", ALL, []),
    ("guanciale", "cured_meat", "g", ALL, []),
    ("pancetta", "cured_meat", "g", ALL, []),
    ("prosciutto cotto", "cured_meat", "g", ALL, []),
    ("prosciutto crudo", "cured_meat", "g", ALL, []),
    ("salsiccia", "cured_meat", "g", ALL, ["salsicce"]),
    ("speck", "cured_meat", "g", ALL, []),
    ("carne macinata di manzo", "red_meat", "g", ALL, ["macinato", "carne macinata"]),
    ("manzo", "red_meat", "g", ALL, []),
    ("maiale", "red_meat", "g", ALL, ["lonza di maiale"]),
    ("vitello", "red_meat", "g", ALL, ["fesa di vitello"]),
    ("agnello", "red_meat", "g", ALL, []),
    ("pollo", "white_meat", "g", ALL, ["cosce di pollo"]),
    ("petto di pollo", "white_meat", "g", ALL, []),
    ("tacchino", "white_meat", "g", ALL, ["fesa di tacchino"]),
    ("coniglio", "white_meat", "g", ALL, []),
    # -- fish and seafood
    ("acciuga", "fish", "g", [4, 5, 6, 7, 8, 9], ["acciughe", "alici"]),
    ("acciuga sott'olio", "fish", "g", ALL, ["filetti di acciuga"]),
    ("baccalà", "fish", "g", ALL, []),
    ("branzino", "fish", "pc", ALL, ["spigola"]),
    ("merluzzo", "fish", "g", ALL, []),
    ("orata", "fish", "pc", ALL, []),
    ("pesce spada", "fish", "g", [5, 6, 7, 8, 9], []),
    ("salmone", "fish", "g", ALL, []),
    ("tonno", "fish", "g", [5, 6, 7, 8, 9], ["tonno fresco"]),
    ("tonno in scatola", "fish", "g", ALL, ["tonno sott'olio"]),
    ("calamaro", "seafood", "g", ALL, ["calamari"]),
    ("cozza", "seafood", "g", [5, 6, 7, 8, 9], ["cozze"]),
    ("gambero", "seafood", "g", ALL, ["gamberi", "gamberetti"]),
    ("polpo", "seafood", "g", ALL, ["polipo"]),
    ("vongola", "seafood", "g", ALL, ["vongole"]),
    # -- eggs, dairy, cheese
    ("uovo", "egg", "pc", ALL, ["uova"]),
    ("tuorlo", "egg", "pc", ALL, ["tuorli", "tuorlo d'uovo"]),
    ("albume", "egg", "pc", ALL, ["albumi"]),
    ("latte", "dairy", "ml", ALL, ["latte intero"]),
    ("panna da cucina", "dairy", "ml", ALL, ["panna"]),
    ("panna fresca", "dairy", "ml", ALL, ["panna liquida"]),
    ("yogurt", "dairy", "g", ALL, ["yogurt bianco", "yogurt bianco naturale"]),
    ("burro", "fat", "g", ALL, []),
    ("fontina", "cheese", "g", ALL, []),
    ("gorgonzola", "cheese", "g", ALL, []),
    ("mascarpone", "cheese", "g", ALL, []),
    ("mozzarella", "cheese", "g", ALL, ["fiordilatte"]),
    ("parmigiano", "cheese", "g", ALL, ["parmigiano reggiano", "grana padano", "grana"]),
    ("pecorino", "cheese", "g", ALL, ["pecorino romano"]),
    ("ricotta", "cheese", "g", ALL, []),
    ("scamorza", "cheese", "g", ALL, ["provola"]),
    ("stracchino", "cheese", "g", ALL, ["crescenza"]),
    # -- fats
    ("olio extravergine d'oliva", "fat", "ml", ALL, ["olio evo", "olio d'oliva"]),
    ("olio di semi", "fat", "ml", ALL, ["olio di semi di girasole"]),
    # -- nuts and seeds
    ("mandorla", "nut_seed", "g", ALL, ["mandorle"]),
    ("nocciola", "nut_seed", "g", ALL, ["nocciole"]),
    ("noce", "nut_seed", "g", ALL, ["noci", "gherigli di noce"]),
    ("pinolo", "nut_seed", "g", ALL, ["pinoli"]),
    ("pistacchio", "nut_seed", "g", ALL, ["pistacchi"]),
    ("semi di sesamo", "nut_seed", "g", ALL, ["sesamo"]),
    # -- herbs and spices
    ("alloro", "herb_spice", "pc", ALL, ["foglie di alloro"]),
    ("basilico", "herb_spice", "g", [6, 7, 8, 9], []),
    ("cannella", "herb_spice", "tt", ALL, []),
    ("erba cipollina", "herb_spice", "g", [4, 5, 6, 7, 8, 9], []),
    ("menta", "herb_spice", "g", [5, 6, 7, 8, 9], []),
    ("noce moscata", "herb_spice", "tt", ALL, []),
    ("origano", "herb_spice", "tt", ALL, []),
    ("paprika", "herb_spice", "tt", ALL, ["paprika dolce", "paprika affumicata"]),
    ("pepe nero", "herb_spice", "tt", ALL, ["pepe"]),
    ("peperoncino", "herb_spice", "tt", ALL, []),
    ("prezzemolo", "herb_spice", "g", ALL, []),
    ("rosmarino", "herb_spice", "g", ALL, []),
    ("salvia", "herb_spice", "g", ALL, []),
    ("timo", "herb_spice", "g", ALL, []),
    ("zafferano", "herb_spice", "tt", ALL, ["pistilli di zafferano"]),
    ("curry", "herb_spice", "tt", ALL, []),
    ("zenzero", "herb_spice", "g", ALL, []),
    # -- condiments and pantry
    ("aceto balsamico", "condiment", "ml", ALL, []),
    ("aceto di vino", "condiment", "ml", ALL, ["aceto di vino bianco", "aceto"]),
    ("brodo vegetale", "condiment", "ml", ALL, ["brodo"]),
    ("cappero", "condiment", "g", ALL, ["capperi"]),
    ("maionese", "condiment", "g", ALL, []),
    ("sale", "condiment", "tt", ALL, ["sale fino", "sale grosso"]),
    ("salsa di soia", "condiment", "ml", ALL, []),
    ("senape", "condiment", "g", ALL, []),
    ("vino bianco", "condiment", "ml", ALL, []),
    ("vino rosso", "condiment", "ml", ALL, []),
    ("acqua", "other", "ml", ALL, []),
    ("lievito di birra", "other", "g", ALL, []),
    ("lievito per dolci", "other", "g", ALL, ["lievito vanigliato", "lievito"]),
    # -- sweet
    ("cacao amaro", "sweetener", "g", ALL, ["cacao"]),
    ("cioccolato fondente", "sweetener", "g", ALL, ["cioccolato"]),
    ("miele", "sweetener", "g", ALL, []),
    ("zucchero", "sweetener", "g", ALL, ["zucchero semolato"]),
    ("zucchero a velo", "sweetener", "g", ALL, []),
    ("zucchero di canna", "sweetener", "g", ALL, []),
]


def seed(apps, schema_editor):
    Ingredient = apps.get_model("catalog", "Ingredient")
    known = set()
    for name, aliases in Ingredient.objects.values_list("name", "aliases"):
        known.add(name)
        known.update(aliases or [])
    for name, category, unit, months, aliases in INGREDIENTS:
        if name in known or known.intersection(aliases):
            continue  # already there, possibly under another name: leave it as it is
        Ingredient.objects.create(
            name=name,
            category=category,
            default_unit=unit,
            season_months=sorted(months),
            aliases=sorted(set(aliases) - {name}),
        )
        known.add(name)
        known.update(aliases)


class Migration(migrations.Migration):
    dependencies = [("catalog", "0004_kitchen_tool_codes")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
