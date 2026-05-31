"""
champions_pokedex.py
Parcha el Pokédex de poke-env Gen9 con los datos de las Mega Evoluciones de Pokémon Champions.
Stats obtenidos de: game8.co/games/Pokemon-Champions/archives/592472
Los stats de Champions son los originales del juego (sin el +75 HP / +20 otros de Champions).
Llamar a parchear_pokedex_champions() al arrancar el bot antes de cualquier combate.
"""

from poke_env.data import GenData

# Datos de todas las Megas disponibles en Reg M-A
# Formato: "nombre_poke_env": {"hp","atk","def","spa","spd","spe","types","ability"}
# Los tipos siguen el formato de poke-env en mayúsculas
MEGAS_CHAMPIONS = {
    "venusaurmega": {
        "hp": 80, "atk": 100, "def": 123, "spa": 122, "spd": 120, "spe": 80,
        "types": ["GRASS", "POISON"], "ability": "thickfat",
    },
    "charizardmegax": {
        "hp": 78, "atk": 130, "def": 111, "spa": 130, "spd": 85, "spe": 100,
        "types": ["FIRE", "DRAGON"], "ability": "toughclaws",
    },
    "charizardmegay": {
        "hp": 78, "atk": 104, "def": 78, "spa": 159, "spd": 115, "spe": 100,
        "types": ["FIRE", "FLYING"], "ability": "drought",
    },
    "blastoisemega": {
        "hp": 79, "atk": 103, "def": 120, "spa": 135, "spd": 115, "spe": 78,
        "types": ["WATER"], "ability": "megalauncher",
    },
    "beedrillmega": {
        "hp": 65, "atk": 150, "def": 40, "spa": 15, "spd": 80, "spe": 145,
        "types": ["BUG", "POISON"], "ability": "adaptability",
    },
    "pidgeotmega": {
        "hp": 83, "atk": 80, "def": 80, "spa": 135, "spd": 80, "spe": 121,
        "types": ["NORMAL", "FLYING"], "ability": "noguard",
    },
    "clefablemega": {
        "hp": 95, "atk": 80, "def": 93, "spa": 135, "spd": 110, "spe": 70,
        "types": ["FAIRY"], "ability": "magicbounce",
    },
    "alakazammega": {
        "hp": 55, "atk": 50, "def": 65, "spa": 175, "spd": 105, "spe": 150,
        "types": ["PSYCHIC"], "ability": "trace",
    },
    "victreebelmega": {
        "hp": 80, "atk": 125, "def": 85, "spa": 135, "spd": 95, "spe": 70,
        "types": ["GRASS", "POISON"], "ability": "innardsout",
    },
    "slowbromega": {
        "hp": 95, "atk": 75, "def": 180, "spa": 130, "spd": 80, "spe": 30,
        "types": ["WATER", "PSYCHIC"], "ability": "shellarmor",
    },
    "gengarmega": {
        "hp": 60, "atk": 65, "def": 80, "spa": 170, "spd": 95, "spe": 130,
        "types": ["GHOST", "POISON"], "ability": "shadowtag",
    },
    "kangaskhanmega": {
        "hp": 105, "atk": 125, "def": 100, "spa": 60, "spd": 100, "spe": 100,
        "types": ["NORMAL"], "ability": "parentalbond",
    },
    "starmiemega": {
        "hp": 60, "atk": 100, "def": 105, "spa": 130, "spd": 105, "spe": 120,
        "types": ["WATER", "PSYCHIC"], "ability": "hugepower",
    },
    "pinsirmega": {
        "hp": 65, "atk": 155, "def": 120, "spa": 65, "spd": 90, "spe": 105,
        "types": ["BUG", "FLYING"], "ability": "aerilate",
    },
    "gyaradosmega": {
        "hp": 95, "atk": 155, "def": 109, "spa": 70, "spd": 130, "spe": 81,
        "types": ["WATER", "DARK"], "ability": "moldbreaker",
    },
    "aerodactylmega": {
        "hp": 80, "atk": 135, "def": 85, "spa": 70, "spd": 95, "spe": 150,
        "types": ["ROCK", "FLYING"], "ability": "toughclaws",
    },
    "dragonitemega": {
        "hp": 91, "atk": 124, "def": 115, "spa": 145, "spd": 125, "spe": 100,
        "types": ["DRAGON", "FLYING"], "ability": "multiscale",
    },
        "meganiumMega": {
        "hp": 80, "atk": 92, "def": 115, "spa": 143, "spd": 115, "spe": 80,
        "types": ["GRASS"], "ability": "megasol",
    },
    "meganiumite": {
        "hp": 80, "atk": 92, "def": 115, "spa": 143, "spd": 115, "spe": 80,
        "types": ["GRASS"], "ability": "megasol",
    },
    "feraligatrmega": {
        "hp": 85, "atk": 160, "def": 125, "spa": 89, "spd": 93, "spe": 78,
        "types": ["WATER", "DRAGON"], "ability": "dragonize",
    },
    "ampharosmega": {
        "hp": 90, "atk": 95, "def": 105, "spa": 165, "spd": 110, "spe": 45,
        "types": ["ELECTRIC", "DRAGON"], "ability": "moldbreaker",
    },
    "steelixmega": {
        "hp": 75, "atk": 125, "def": 230, "spa": 55, "spd": 95, "spe": 30,
        "types": ["STEEL", "GROUND"], "ability": "sandforce",
    },
    "scizormega": {
        "hp": 70, "atk": 150, "def": 140, "spa": 65, "spd": 100, "spe": 75,
        "types": ["BUG", "STEEL"], "ability": "technician",
    },
    "heracrossmega": {
        "hp": 80, "atk": 185, "def": 115, "spa": 40, "spd": 105, "spe": 75,
        "types": ["BUG", "FIGHTING"], "ability": "skilllink",
    },
    "skarmorymega": {
        "hp": 65, "atk": 140, "def": 110, "spa": 40, "spd": 100, "spe": 110,
        "types": ["STEEL", "FLYING"], "ability": "stalwart",
    },
    "houndoommega": {
        "hp": 75, "atk": 90, "def": 90, "spa": 140, "spd": 90, "spe": 115,
        "types": ["DARK", "FIRE"], "ability": "solarpower",
    },
    "tyranitarmega": {
        "hp": 100, "atk": 164, "def": 150, "spa": 95, "spd": 120, "spe": 71,
        "types": ["ROCK", "DARK"], "ability": "sandstream",
    },
    "gardevoirmega": {
        "hp": 68, "atk": 85, "def": 65, "spa": 165, "spd": 135, "spe": 100,
        "types": ["PSYCHIC", "FAIRY"], "ability": "pixilate",
    },
    "sableyemega": {
        "hp": 50, "atk": 85, "def": 125, "spa": 85, "spd": 115, "spe": 20,
        "types": ["DARK", "GHOST"], "ability": "magicbounce",
    },
    "aggronmega": {
        "hp": 70, "atk": 140, "def": 230, "spa": 60, "spd": 80, "spe": 50,
        "types": ["STEEL"], "ability": "filter",
    },
    "medichamMega": {
        "hp": 60, "atk": 100, "def": 85, "spa": 80, "spd": 85, "spe": 100,
        "types": ["FIGHTING", "PSYCHIC"], "ability": "purepower",
    },
    "medicham-mega": {
        "hp": 60, "atk": 100, "def": 85, "spa": 80, "spd": 85, "spe": 100,
        "types": ["FIGHTING", "PSYCHIC"], "ability": "purepower",
    },
    "manectricmega": {
        "hp": 70, "atk": 75, "def": 80, "spa": 135, "spd": 80, "spe": 135,
        "types": ["ELECTRIC"], "ability": "intimidate",
    },
    "sharpedomega": {
        "hp": 70, "atk": 140, "def": 70, "spa": 110, "spd": 65, "spe": 105,
        "types": ["WATER", "DARK"], "ability": "strongjaw",
    },
    "cameruptmega": {
        "hp": 70, "atk": 120, "def": 100, "spa": 145, "spd": 105, "spe": 20,
        "types": ["FIRE", "GROUND"], "ability": "sheerforce",
    },
    "altariamega": {
        "hp": 75, "atk": 110, "def": 110, "spa": 110, "spd": 105, "spe": 80,
        "types": ["DRAGON", "FAIRY"], "ability": "pixilate",
    },
    "banettemega": {
        "hp": 64, "atk": 165, "def": 75, "spa": 93, "spd": 83, "spe": 75,
        "types": ["GHOST"], "ability": "prankster",
    },
    "chimechomega": {
        "hp": 75, "atk": 50, "def": 110, "spa": 135, "spd": 120, "spe": 65,
        "types": ["PSYCHIC"], "ability": "levitate",
    },
    "absolmega": {
        "hp": 65, "atk": 150, "def": 60, "spa": 115, "spd": 60, "spe": 115,
        "types": ["DARK"], "ability": "magicbounce",
    },
    "glaliemega": {
        "hp": 80, "atk": 120, "def": 80, "spa": 120, "spd": 80, "spe": 100,
        "types": ["ICE"], "ability": "refrigerate",
    },
    "lopunnymega": {
        "hp": 65, "atk": 136, "def": 94, "spa": 54, "spd": 96, "spe": 135,
        "types": ["NORMAL", "FIGHTING"], "ability": "scrappy",
    },
    "garchompmega": {
        "hp": 108, "atk": 170, "def": 115, "spa": 120, "spd": 95, "spe": 92,
        "types": ["DRAGON", "GROUND"], "ability": "sandforce",
    },
    "lucariomega": {
        "hp": 70, "atk": 145, "def": 88, "spa": 140, "spd": 70, "spe": 112,
        "types": ["FIGHTING", "STEEL"], "ability": "adaptability",
    },
    "abomasnowmega": {
        "hp": 90, "atk": 132, "def": 105, "spa": 132, "spd": 105, "spe": 30,
        "types": ["GRASS", "ICE"], "ability": "snowwarning",
    },
    "gallademega": {
        "hp": 68, "atk": 165, "def": 95, "spa": 65, "spd": 115, "spe": 110,
        "types": ["PSYCHIC", "FIGHTING"], "ability": "innerfocus",
    },
    "frosslassmega": {
        "hp": 70, "atk": 80, "def": 70, "spa": 140, "spd": 100, "spe": 120,
        "types": ["ICE", "GHOST"], "ability": "snowwarning",
    },
    "embro armega": {
        "hp": 110, "atk": 148, "def": 75, "spa": 110, "spd": 110, "spe": 75,
        "types": ["FIRE", "FIGHTING"], "ability": "moldbreaker",
    },
    "excadrillmega": {
        "hp": 110, "atk": 165, "def": 100, "spa": 65, "spd": 65, "spe": 103,
        "types": ["GROUND", "STEEL"], "ability": "piercingdrill",
    },
    "audinomega": {
        "hp": 103, "atk": 60, "def": 126, "spa": 80, "spd": 126, "spe": 50,
        "types": ["NORMAL", "FAIRY"], "ability": "healer",
    },
    "chandeluremega": {
        "hp": 60, "atk": 75, "def": 110, "spa": 175, "spd": 110, "spe": 90,
        "types": ["GHOST", "FIRE"], "ability": "infiltrator",
    },
    "golurkmega": {
        "hp": 89, "atk": 159, "def": 105, "spa": 70, "spd": 105, "spe": 55,
        "types": ["GROUND", "GHOST"], "ability": "unseenfist",
    },
    "chesnaughtmega": {
        "hp": 88, "atk": 137, "def": 172, "spa": 74, "spd": 115, "spe": 44,
        "types": ["GRASS", "FIGHTING"], "ability": "bulletproof",
    },
    "delphoxmega": {
        "hp": 75, "atk": 69, "def": 72, "spa": 159, "spd": 125, "spe": 134,
        "types": ["FIRE", "PSYCHIC"], "ability": "levitate",
    },
    "greninjamega": {
        "hp": 72, "atk": 125, "def": 77, "spa": 133, "spd": 81, "spe": 142,
        "types": ["WATER", "DARK"], "ability": "protean",
    },
    "floettemega": {
        "hp": 74, "atk": 85, "def": 87, "spa": 155, "spd": 148, "spe": 102,
        "types": ["FAIRY"], "ability": "fairyaura",
    },
    "meowsticmega": {
        "hp": 74, "atk": 48, "def": 76, "spa": 143, "spd": 101, "spe": 124,
        "types": ["PSYCHIC"], "ability": "trace",
    },
    "hawluchamega": {
        "hp": 78, "atk": 137, "def": 100, "spa": 74, "spd": 93, "spe": 118,
        "types": ["FIGHTING", "FLYING"], "ability": "noguard",
    },
    "crabominablemega": {
        "hp": 97, "atk": 157, "def": 122, "spa": 62, "spd": 107, "spe": 33,
        "types": ["ICE", "FIGHTING"], "ability": "ironfist",
    },
    "drampamega": {
        "hp": 78, "atk": 85, "def": 110, "spa": 160, "spd": 116, "spe": 36,
        "types": ["NORMAL", "DRAGON"], "ability": "berserk",
    },
    "scovillainmega": {
        "hp": 65, "atk": 138, "def": 85, "spa": 138, "spd": 85, "spe": 75,
        "types": ["GRASS", "FIRE"], "ability": "spicyspray",
    },
    "glimmoramega": {
        "hp": 83, "atk": 90, "def": 105, "spa": 150, "spd": 96, "spe": 101,
        "types": ["ROCK", "POISON"], "ability": "adaptability",
    },
}

# Nombres alternativos que Showdown puede usar
ALIASES = {
    "meganiumite": "meganiumMega",  # por si Showdown usa el nombre de la piedra
    "dragoninite": "dragonitemega",
    "floette-eternal-mega": "floettemega",
    "floette-mega": "floettemega",
    "charizard-mega-x": "charizardmegax",
    "charizard-mega-y": "charizardmegay",
    "gyarados-mega": "gyaradosmega",
    "kangaskhan-mega": "kangaskhanmega",
    "gengar-mega": "gengarmega",
    "dragonite-mega": "dragonitemega",
    "meganium-mega": "meganiumMega",
}


def _construir_entrada_pokedex(nombre, datos):
    """Construye una entrada compatible con el formato del Pokédex de poke-env."""
    tipos = datos["types"]
    return {
        "num": 9999,  # número ficticio para Megas de Champions
        "name": nombre,
        "types": tipos,
        "baseStats": {
            "hp": datos["hp"],
            "atk": datos["atk"],
            "def": datos["def"],
            "spa": datos["spa"],
            "spd": datos["spd"],
            "spe": datos["spe"],
        },
        "abilities": {"0": datos["ability"]},
        "heightm": 1.0,
        "weightkg": 50.0,
        "color": "Red",
        "tier": "Illegal",
        "isNonstandard": None,
    }


def parchear_pokedex_champions():
    """
    Añade las Mega Evoluciones de Champions al Pokédex de poke-env Gen9 en memoria.
    Llamar una vez al arrancar el bot.
    """
    try:
        pokedex = GenData.from_gen(9).pokedex
        añadidos = 0
        ya_existentes = 0

        for nombre, datos in MEGAS_CHAMPIONS.items():
            clave = nombre.lower().replace("-", "").replace(" ", "")
            if clave not in pokedex:
                pokedex[clave] = _construir_entrada_pokedex(clave, datos)
                añadidos += 1
            else:
                ya_existentes += 1

        # Añadir aliases
        for alias, original in ALIASES.items():
            clave_alias = alias.lower().replace("-", "").replace(" ", "")
            clave_orig = original.lower().replace("-", "").replace(" ", "")
            if clave_alias not in pokedex:
                if clave_orig in pokedex:
                    pokedex[clave_alias] = pokedex[clave_orig]
                    añadidos += 1
                elif clave_orig in {k.lower() for k in MEGAS_CHAMPIONS}:
                    # Buscar en MEGAS_CHAMPIONS con normalización
                    for k, v in MEGAS_CHAMPIONS.items():
                        if k.lower().replace("-", "").replace(" ", "") == clave_orig:
                            pokedex[clave_alias] = _construir_entrada_pokedex(clave_alias, v)
                            añadidos += 1
                            break

        print(f"[Champions Pokédex] Parcheado: {añadidos} Megas añadidas, {ya_existentes} ya existían")
        return True

    except Exception as e:
        print(f"[Champions Pokédex] Error al parchear: {e}")
        return False
