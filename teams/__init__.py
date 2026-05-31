from teams.regg import EQUIPOS_REGG
from teams.regf import EQUIPOS_REGF
from teams.regi import EQUIPOS_REGI
from teams.custom import EQUIPOS_CUSTOM
from teams.regma import EQUIPOS_REGMA

EQUIPOS_POR_REGULACION = {
    "gen9vgc2024regg": EQUIPOS_REGG,
    "gen9vgc2026regf": EQUIPOS_REGF,
    "gen9vgc2026regi": EQUIPOS_REGI,
    "gen9doublescustomgame": EQUIPOS_CUSTOM,
    "gen9championsvgc2026regma": EQUIPOS_REGMA,
}

REGULACIONES = list(EQUIPOS_POR_REGULACION.keys())