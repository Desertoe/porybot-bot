import asyncio
import os
import sys
import random
import math
from dotenv import load_dotenv
from google import genai
from google.genai import types
from poke_env.player import Player
from poke_env.player.battle_order import DoubleBattleOrder
from poke_env import AccountConfiguration, ShowdownServerConfiguration
from poke_env.battle.double_battle import DoubleBattle
from poke_env.battle.field import Field
from poke_env.battle.side_condition import SideCondition
from poke_env.data import GenData
from teams import EQUIPOS_POR_REGULACION

load_dotenv()

GEN_DATA = GenData.from_gen(9)
TYPE_CHART = GEN_DATA.type_chart


def calcular_daño_aproximado(atacante, movimiento, defensor, battle=None, def_mult_conocido=1.0):
    """
    Calcula rango de daño aproximado (mínimo-máximo) en % del HP del defensor.
    Usa stats reales del atacante y stats base del defensor si no conocemos sus EVs.
    def_mult_conocido: multiplicador para ajustar la defensa si hemos inferido EVs (>1 = más bulk)
    """
    try:
        bp = movimiento.base_power
        if bp == 0:
            return None

        # Movimientos multi-hit con mecánicas especiales
        mov_id = movimiento.id.lower()
        # Surging Strikes: exactamente 3 hits, siempre crítico → 25*3*1.5 = 112 BP efectivo
        if mov_id == "surgingstrikes":
            bp = 112
        # Wicked Blow y Glacier Lance: siempre crítico → x1.5
        elif mov_id in ("wickedblow", "glaciallance"):
            bp = int(bp * 1.5)
        # Triple Axel: 3 hits con BP creciente 20+40+60, promedio ponderado ~80
        elif mov_id == "tripleaxel":
            bp = 80
        # Movimientos de 2 hits fijos
        elif mov_id in ("dualwingbeat", "doublekick", "bonemerang", "doublehit", "geargrind"):
            bp = bp * 2
        # Movimientos de ráfaga 2-5 hits (probabilidad: 2=37.5%, 3=37.5%, 4=12.5%, 5=12.5%)
        # Promedio estadístico: ~3.17 hits. Usamos 3 como estimación conservadora
        # pero marcamos en el prompt que es variable
        elif mov_id in ("bulletseed", "rockblast", "pinmissile", "watershuriken",
                        "populationbomb", "tailslap", "spikecannon", "barrage",
                        "furyattack", "furyswipes", "bonerush"):
            bp = bp * 3  # promedio conservador, se nota en prompt como variable

        # Stats del atacante
        if movimiento.category.name == "PHYSICAL":
            atk_stat = "atk"
            def_stat = "def"
        else:
            atk_stat = "spa"
            def_stat = "spd"

        # Ataque del atacante (stats reales si disponibles)
        if hasattr(atacante, 'stats') and atacante.stats and atacante.stats.get(atk_stat):
            atk = atacante.stats[atk_stat]
        elif hasattr(atacante, 'base_stats') and atacante.base_stats:
            base = atacante.base_stats.get(atk_stat, 50)
            atk = math.floor((2 * base + 31 + 63) * 50 / 100) + 5  # EVs 252, IV 31, neutra
        else:
            return None

        # Multiplicador por objeto ofensivo del atacante
        objeto_atk_mult = 1.0
        if hasattr(atacante, 'item') and atacante.item:
            item = atacante.item.lower()
            if item == "choiceband" and atk_stat == "atk":
                objeto_atk_mult = 1.5
            elif item == "choicespecs" and atk_stat == "spa":
                objeto_atk_mult = 1.5
            elif item == "lifeorb":
                objeto_atk_mult = 1.3
            elif item in ("muscleband",) and atk_stat == "atk":
                objeto_atk_mult = 1.1
            elif item in ("wiseglasses",) and atk_stat == "spa":
                objeto_atk_mult = 1.1
        atk = math.floor(atk * objeto_atk_mult)

        # Multiplicador de habilidad ofensiva del atacante
        if hasattr(atacante, 'ability') and atacante.ability:
            hab = atacante.ability.lower()
            tipo_mov = movimiento.type
            if hab == "sheerforce" and movimiento.secondary:
                objeto_atk_mult = 1.3  # aproximación
                atk = math.floor(atk * 1.3 / objeto_atk_mult)  # evitar doble aplicación
            elif hab == "technician" and movimiento.base_power <= 60:
                atk = math.floor(atk * 1.5)
            elif hab == "dragonsmaw" and tipo_mov and tipo_mov.name == "DRAGON":
                atk = math.floor(atk * 1.5)
            elif hab == "transistor" and tipo_mov and tipo_mov.name == "ELECTRIC":
                atk = math.floor(atk * 1.5)

        # Defensa del defensor (asumimos EVs estándar si no conocemos)
        if hasattr(defensor, 'stats') and defensor.stats and defensor.stats.get(def_stat):
            def_ = defensor.stats[def_stat]
        elif hasattr(defensor, 'base_stats') and defensor.base_stats:
            base = defensor.base_stats.get(def_stat, 50)
            def_ = math.floor((2 * base + 31 + 63) * 50 / 100) + 5
        else:
            return None

        # Multiplicador por objeto defensivo del defensor
        objeto_def_mult = 1.0
        if hasattr(defensor, 'item') and defensor.item:
            item = defensor.item.lower()
            if item == "eviolite":
                objeto_def_mult = 1.5
            elif item == "assaultvest":
                if def_stat == "spd":
                    objeto_def_mult = 1.5
            elif item in ("rockyhelmet",):
                pass  # No afecta defensa directamente
        def_ = math.floor(def_ * objeto_def_mult * def_mult_conocido)

        # HP del defensor
        if hasattr(defensor, 'stats') and defensor.stats and defensor.stats.get('hp'):
            hp_max = defensor.stats['hp']
        elif hasattr(defensor, 'base_stats') and defensor.base_stats:
            base_hp = defensor.base_stats.get('hp', 50)
            hp_max = math.floor((2 * base_hp + 31 + 63) * 50 / 100) + 60
        else:
            return None

        # Aplicar boosts del atacante
        atk_boost = atacante.boosts.get(atk_stat, 0)
        if atk_boost > 0:
            atk = math.floor(atk * (2 + atk_boost) / 2)
        elif atk_boost < 0:
            atk = math.floor(atk * 2 / (2 - atk_boost))

        # Aplicar boosts del defensor
        def_boost = defensor.boosts.get(def_stat, 0)
        if def_boost > 0:
            def_ = math.floor(def_ * (2 + def_boost) / 2)
        elif def_boost < 0:
            def_ = math.floor(def_ * 2 / (2 - def_boost))

        # Fórmula base de daño Gen 9
        daño_base = math.floor(math.floor(math.floor(2 * 50 / 5 + 2) * bp * atk / def_) / 50) + 2

        # Modificador de tipo
        tipo_mov = movimiento.type
        mult = tipo_mov.damage_multiplier(
            defensor.type_1, defensor.type_2,
            type_chart=TYPE_CHART
        )
        if mult == 0:
            return None  # Inmune

        # STAB
        atk_types = [atacante.type_1]
        if atacante.type_2:
            atk_types.append(atacante.type_2)
        stab = 1.5 if tipo_mov in atk_types else 1.0

        # Clima
        clima_mult = 1.0
        if battle:
            try:
                weather = battle.weather
                if isinstance(weather, dict):
                    weather = next(iter(weather), None)
                if weather:
                    w_name = weather.name if hasattr(weather, 'name') else str(weather)
                    if "SUN" in w_name and tipo_mov.name == "FIRE":
                        clima_mult = 1.5
                    elif "SUN" in w_name and tipo_mov.name == "WATER":
                        clima_mult = 0.5
                    elif "RAIN" in w_name and tipo_mov.name == "WATER":
                        clima_mult = 1.5
                    elif "RAIN" in w_name and tipo_mov.name == "FIRE":
                        clima_mult = 0.5
            except Exception:
                pass

        daño_final = daño_base * mult * stab * clima_mult

        # Modificadores de habilidad del atacante
        habilidad_mult = 1.0
        if hasattr(atacante, 'ability') and atacante.ability:
            hab = atacante.ability.lower()
            if hab == "sheerforce" and movimiento.secondary:
                habilidad_mult *= 1.3
            elif hab == "swordofruin" and atk_stat == "atk":
                habilidad_mult *= 1.0  # Sword of Ruin baja Def del defensor (ya aplicado externamente)
            elif hab == "adaptability" and stab > 1.0:
                habilidad_mult *= 4/3  # Adaptability: STAB 2x en vez de 1.5x
                stab = 1.0  # Ya lo aplicamos arriba, compensamos

        # Modificadores de habilidad que bajan stats (Ruins)
        # Sword of Ruin en campo: baja Def de todos excepto el usuario
        # Beads of Ruin en campo: baja SpD de todos excepto el usuario
        ruin_mult = 1.0
        if battle:
            for p in battle.opponent_active_pokemon:
                if p and hasattr(p, 'ability') and p.ability:
                    hab_rival = p.ability.lower()
                    if hab_rival == "swordofruin" and def_stat == "def":
                        ruin_mult *= 0.75  # Baja Def a 3/4
                    elif hab_rival == "beadsofruin" and def_stat == "spd":
                        ruin_mult *= 0.75  # Baja SpD a 3/4
            for p in battle.active_pokemon:
                if p and hasattr(p, 'ability') and p.ability:
                    hab_propio = p.ability.lower()
                    if hab_propio == "swordofruin" and def_stat == "def" and p != atacante:
                        ruin_mult *= 0.75
                    elif hab_propio == "beadsofruin" and def_stat == "spd" and p != atacante:
                        ruin_mult *= 0.75

        # Grassy Terrain: debilita Earthquake a 0.5
        terreno_mult = 1.0
        if battle and movimiento.id.lower() == "earthquake":
            try:
                terrain = battle.fields
                if terrain and any("GRASSY" in str(t) for t in terrain):
                    terreno_mult = 0.5
            except Exception:
                pass

        # Multiplicador de spread move en dobles (0.75 si hay múltiples objetivos)
        spread_mult = 1.0
        if hasattr(movimiento, 'target') and movimiento.target:
            target_name = movimiento.target.name if hasattr(movimiento.target, 'name') else str(movimiento.target)
            if target_name in ("ALL_ADJACENT", "ALL_ADJACENT_FOES"):
                # En dobles, si hay más de 1 rival activo el movimiento hace 75%
                n_rivales = len([p for p in (battle.opponent_active_pokemon if battle else []) if p is not None])
                if n_rivales > 1:
                    spread_mult = 0.75

        # Multiplicador de pantallas defensivas (Reflect, Light Screen, Aurora Veil)
        pantalla_mult = 1.0
        if battle:
            try:
                # Determinar si el defensor es nuestro Pokémon o del rival
                defensor_es_propio = any(
                    p is defensor for p in battle.active_pokemon if p is not None
                )
                condiciones = battle.side_conditions if defensor_es_propio else battle.opponent_side_conditions
                # Aurora Veil reduce daño físico y especial a 0.5 en singles, ~0.66 en dobles
                if any("AURORA_VEIL" in str(c) for c in condiciones):
                    pantalla_mult *= 0.5
                # Reflect reduce daño físico
                elif atk_stat == "atk" and any("REFLECT" in str(c) for c in condiciones):
                    pantalla_mult *= 0.5
                # Light Screen reduce daño especial
                elif atk_stat == "spa" and any("LIGHT_SCREEN" in str(c) for c in condiciones):
                    pantalla_mult *= 0.5
            except Exception:
                pass

        daño_final = daño_final * habilidad_mult * ruin_mult * terreno_mult * spread_mult * pantalla_mult

        # Rango (85% - 100% del daño calculado)
        daño_min = math.floor(daño_final * 0.85)
        daño_max = math.floor(daño_final)

        # Convertir a porcentaje del HP actual del defensor
        hp_actual = math.floor(hp_max * defensor.current_hp_fraction)
        if hp_actual == 0:
            return None

        pct_min = round(daño_min / hp_max * 100, 1)
        pct_max = round(daño_max / hp_max * 100, 1)

        return pct_min, pct_max, mult

    except Exception:
        return None

FORMATO_POR_ARG = {
    "regg": "gen9vgc2024regg",
    "regf": "gen9vgc2026regf",
    "regi": "gen9vgc2026regi",
    "regma": "gen9championsvgc2026regma",
    "custom": "gen9doublescustomgame",
}

ERRORES_FILE = "errores_aprendidos.txt"
MAX_ERRORES = 15  # Máximo de errores a incluir en el prompt

def cargar_errores_aprendidos():
    """Carga los errores más recientes del archivo de aprendizaje."""
    try:
        if not os.path.exists(ERRORES_FILE):
            return ""
        with open(ERRORES_FILE, "r", encoding="utf-8") as f:
            lineas = [l.strip() for l in f.readlines() if l.strip()]
        if not lineas:
            return ""
        # Tomar los últimos MAX_ERRORES errores
        errores_recientes = lineas[-MAX_ERRORES:]
        return "\n\nERRORES RECIENTES QUE DEBES EVITAR (aprendidos de combates anteriores):\n" + \
               "\n".join(f"- {e}" for e in errores_recientes) + "\n"
    except Exception:
        return ""

def guardar_errores(nuevos_errores):
    """Añade nuevos errores al archivo de aprendizaje."""
    try:
        with open(ERRORES_FILE, "a", encoding="utf-8") as f:
            for error in nuevos_errores:
                f.write(error.strip() + "\n")
    except Exception as e:
        print(f"[Error guardando errores: {e}]")

SYSTEM_PROMPT = """Eres un experto en Pokémon VGC (Video Game Championships) competitivo dobles.
Conoces todas las mecánicas del juego: efectividades de tipo, habilidades, objetos, condiciones de campo,
estrategias competitivas, y el meta actual.

Tu objetivo es tomar las mejores decisiones posibles en cada turno del combate.

Reglas importantes de VGC:
- Formato dobles: 2 Pokémon en campo por lado
- Nivel 50, Open Team Sheet activo
- Protect falla si se usa dos veces seguidas (incluye Detect, Wide Guard, Quick Guard)
- Grassy Terrain (de Grassy Surge de Rillaboom): restaura HP, potencia movimientos Planta, debilita Earthquake a la mitad
- Protean (Greninja): cambia el tipo del Pokémon al tipo del movimiento que usa, ganando STAB en todos sus ataques
- Technician (Scizor): potencia movimientos de 60 BP o menos en x1.5 (Bullet Punch pasa de 40 a 60 efectivo)
- Unaware (Quagsire): ignora los boosts de stats del rival al calcular daño recibido y hecho
- Gooey (Goodra): baja la velocidad del rival al contacto físico
- Fake Out, First Impression y otros movimientos de "primer turno" SOLO funcionan cuando el Pokémon indica [PRIMER TURNO EN CAMPO]. Si indica [NO es primer turno] estos movimientos fallarán aunque estén disponibles
- Fake Out tiene BP 40 pero su valor REAL es el flinch: impide que el objetivo actúe ese turno. Úsalo en el turno 1 para neutralizar una amenaza clave (el Pokémon rival más rápido o más peligroso) mientras tu otro Pokémon actúa libremente. Es una de las jugadas más poderosas del turno 1
- Surging Strikes (Urshifu-Rapid-Strike): ataca 3 veces seguidas y SIEMPRE crítica. Su daño real equivale a ~112 BP ignorando modificadores de defensa. Es mucho más poderoso de lo que parece por su BP base de 25. Además ignora Protect gracias a Unseen Fist
- Wicked Blow (Urshifu-Single-Strike): siempre crítico, equivale a 1.5x su BP base
- Movimientos de ráfaga variable (Bullet Seed, Rock Blast, Population Bomb, etc.): atacan 2-5 veces. El daño mostrado es el promedio (~3 hits). Con 2 hits pueden no hacer KO cuando se espera, con 5 hits pueden sorprender. Considera el riesgo antes de depender de ellos para un KO
- Sleep Clause: por respeto al fair play competitivo, NUNCA duermas a más de un Pokémon rival al mismo tiempo
- Los stats reales de cada Pokémon aparecen en el estado — úsalos para comparar velocidades y calcular si un ataque puede hacer KO

CLIMA Y DAÑO RESIDUAL:
- NIEVE (Snow/Snowscape en Gen 9): NO causa daño residual a ningún Pokémon. Solo activa efectos de habilidades (Snow Warning, Ice Body, Slush Rush) y hace que Blizzard tenga 100% de precisión. NO asumas que el rival morirá por daño de nieve.
- ARENA (Sandstorm): SÍ causa daño residual (1/16 HP por turno) a todos excepto Roca, Acero y Tierra.
- LLUVIA y SOL: no causan daño residual.

RECOIL Y ROCKY HELMET:
- Movimientos de recoil (Wave Crash, Double-Edge, Flare Blitz, etc.) ya causan daño al usuario (25-33% del daño infligido)
- Rocky Helmet causa 1/6 del HP máximo del atacante al hacer contacto físico
- Si usas un movimiento de recoil contra un Pokémon con Rocky Helmet, recibes DOBLE penalización: el recoil del movimiento MÁS el Rocky Helmet
- NUNCA uses movimientos de recoil contra Rocky Helmet si estás a menos del 50% de HP — es muy probable que sea suicida

COMMANDER (Tatsugiri + Dondozo):
- Si tu Tatsugiri entra en campo con Dondozo activo, Commander se activa automáticamente
- Tatsugiri queda DENTRO de Dondozo — NO puede atacar, cambiar ni recibir daño directamente
- Dondozo recibe +2 en TODOS sus stats (Atk, Def, SpA, SpD, Spe)
- Tatsugiri solo puede actuar si Dondozo es debilitado
- Si el rival tiene Commander activo, su Tatsugiri está protegido dentro de Dondozo — NO puedes atacarlo directamente
- Para ganar contra Commander: elimina a Dondozo (Tatsugiri saldrá solo) o usa movimientos que afecten a todo el campo
- Si un Pokémon lleva Choice Band/Specs/Scarf y ya usó un movimiento, queda BLOQUEADO en ese movimiento el resto del tiempo que esté en campo
- La única forma de desbloquear es cambiar de Pokémon y volver a entrar
- Si el Pokémon muestra [BLOQUEADO en: X], SOLO puede usar ese movimiento o hacer switch
- NUNCA intentes usar otro movimiento si el Pokémon está bloqueado

TRAPPING (Infestation, Fire Spin, Wrap, Whirlpool, Sand Tomb, etc.):
- Si un Pokémon está atrapado por un movimiento de trampa, NO PUEDE hacer switch mientras dure el efecto
- La trampa dura 4-5 turnos y causa daño al final de cada turno
- Si el Pokémon muestra [ATRAPADO por: X], no puede cambiar

YAWN:
- Yawn no causa sueño inmediato. El Pokémon se dormirá al FINAL del siguiente turno
- Protect NO evita el sueño de Yawn — el contador sigue aunque el Pokémon se proteja
- La única forma de evitar el sueño de Yawn es cambiar de Pokémon antes de que llegue

BAJADAS DE STATS ACUMULADAS:
- Overheat baja SpA en -2 cada vez que se usa. Si el Pokémon tiene SpA -2 o menos, el daño de Overheat cae drásticamente
- A -2 SpA: hace ~56% del daño normal. A -4 SpA: hace ~33% del daño normal. A -6 SpA: hace ~25%
- Considera cambiar o usar otro movimiento cuando el SpA esté muy bajado

POKÉMON DORMIDO:
- Un Pokémon dormido NO puede usar movimientos ofensivos ni de soporte
- Solo puede "dormir" (pasar turno) hasta que se despierte (1-3 turnos)
- Si tu Pokémon está dormido, usa el otro activo de forma independiente y no cuentes con el dormido

La Teracristalización cambia el tipo del Pokémon. Solo puedes teracristalizar si el Pokémon muestra [Tera disponible]. Una vez usada no puede repetirse en todo el combate.
- Tera Stellar mantiene tipos originales, solo añade STAB temporal
- Terapagos al teracristalizar ELIMINA todos los terrenos activos

MEGA EVOLUCIÓN (formato Pokémon Champions Reg M-A):
- En el formato gen9championsvgc2026regma NO hay Teracristalización — en su lugar existe Mega Evolución
- Un Pokémon puede Mega Evolucionar si lleva su Mega Stone (ej: Kangaskhanite, Gyaradosite, Gengarite...)
- La Mega Evolución cambia el tipo, stats y habilidad del Pokémon permanentemente durante el combate
- Solo se puede Mega Evolucionar UNA VEZ por combate (un solo Pokémon del equipo)
- Se activa junto con el movimiento elegido ese turno: ACCION_P1: bodyslam rival1 mega
- Items muy limitados en este formato: NO hay Choice Band/Specs/Scarf, Life Orb, Rocky Helmet, Assault Vest
- Items disponibles: Focus Sash, Sitrus Berry, Lum Berry, Bright Powder, Soft Sand, Mystic Water, etc.
- Mega Kangaskhan: Parental Bond golpea dos veces (el segundo golpe hace 25% del primero)
- Mega Gyarados: cambia a Agua/Siniestro, pierde levitar, gana Mold Breaker
- Mega Gengar: gana Shadow Tag (el rival no puede cambiar), cambia a Fantasma/Veneno

- Tailwind dura 4 turnos, dobla velocidad
- Trick Room dura 5 turnos, invierte velocidad
- Earthquake y otros movimientos de área afectan al aliado también
- SPREAD MOVES en dobles: Earthquake, Rock Slide, Dazzling Gleam, Icy Wind, Heat Wave, Muddy Water y cualquier movimiento que golpee múltiples objetivos hacen solo el 75% del daño normal.
- Wide Guard bloquea movimientos que afectan a múltiples objetivos
- Intimidate baja Atk al entrar en campo
- Prankster da prioridad +1 a movimientos de estado, NO funciona contra tipos Siniestro
- Encore obliga al objetivo a repetir el último movimiento 3 turnos

PREDICT DE SWITCHES DEL RIVAL:
- El rival eligió 4 de sus 6 Pokémon. Los que ya aparecieron están CONFIRMADOS. Los del OTS que no han aparecido son POSIBLES pero no seguros.
- Para predecir un switch considera: ¿tiene el rival un Pokémon en el banco confirmado que resiste mejor tu ataque principal? ¿Está el rival en desventaja y necesita un cambio de estrategia?
- Si el rival tiene Dondozo activo y Tatsugiri en los posibles, es MUY probable que lo tenga seleccionado — prepárate para Commander
- NUNCA asumas que un Pokémon posible ya está en campo o en el banco si no lo has visto — solo razónalo como amenaza potencial

ANÁLISIS DE VICTORIA — OBLIGATORIO EN CADA TURNO:
Antes de elegir tu acción, responde mentalmente estas preguntas y úsalas en tu RAZONAMIENTO:
1. ¿Puedo hacer KO a algún rival este turno? Si sí, hazlo — no desperdicies turnos
2. ¿Qué puede hacer el rival este turno que arruine mi plan? ¿Cómo lo evito?
3. ¿Cuál es la secuencia óptima de los próximos 2 turnos para ganar?
4. Si estoy en POSICIÓN DIFÍCIL, necesito una jugada de alto riesgo/alto impacto — no jugar conservador me hace perder igual pero más lento

REGLA DE ORO DEL ENDGAME: Si tienes ventaja numérica (más Pokémon que el rival), sé agresivo — cada turno que el rival sobrevive es una oportunidad para que revierta la situación. Si estás en desventaja, busca el KO de alto impacto que cambie el juego, no el desgaste lento.

CUÁNDO NO USAR PROTECT:
- Si el rival tiene solo 1 Pokémon activo a menos del 30% HP y tú puedes hacerle KO con un ataque, ataca — no protejas
- Si ambos rivales están debilitados o a muy baja vida, proteger es desperdiciar un turno
- Si ya usaste Protect el turno anterior con ese Pokémon, NO puedes volver a usarlo (fallará)
- Protect es útil para: sobrevivir un turno clave, scoutear el movimiento del rival, esperar que un aliado actúe primero, o evitar un KO cuando no tienes otra opción
- Protect es un desperdicio cuando: el rival puede hacer KO a otro de tus Pokémon ese turno y tú no haces nada para evitarlo, o cuando tienes ventaja numérica clara

CUÁNDO USAR TERA:
- Si el ANÁLISIS DE VICTORIA muestra "TERA RECOMENDADA" o "TERA OFENSIVA", considérala seriamente
- Usa tera defensiva cuando un rival puede hacerte KO y la tera reduce esa debilidad
- Usa tera ofensiva cuando necesitas el STAB extra para garantizar un KO decisivo
- La tera es más valiosa en el mid/endgame cuando el resultado está en juego
- NO uses tera en el turno 1 salvo que sea completamente necesario para sobrevivir
- La tera es una sola vez por combate — úsala en el momento más impactante, no la guardes indefinidamente

- Prioridad +2: Extreme Speed, Feint
- Prioridad +1: Fake Out, Quick Attack, Aqua Jet, Bullet Punch, Mach Punch, Sucker Punch*, Thunderclap*, Shadow Sneak, Water Shuriken, Accelerock, Grassy Glide (en Grassy Terrain)
- Prioridad +1 con Prankster: TODOS los movimientos de estado de Pokémon con Prankster (Tailwind, Spore, Thunder Wave, Encore, etc.) — actúan ANTES que cualquier ataque aunque el Pokémon sea lento
- *Sucker Punch y Thunderclap FALLAN si el rival no está usando un ataque ese turno
- Prioridad -1: Trick Room, Vital Throw
IMPORTANTE: Si el rival tiene Extreme Speed o Sucker Punch disponibles, SIEMPRE considera que pueden actuar antes que tus Pokémon incluso con Tailwind

ROCKY HELMET + RECOIL:
- Rocky Helmet hace 1/6 del HP máximo del atacante si recibe contacto físico
- Movimientos con recoil propio (Wave Crash, Double-Edge, Brave Bird) + Rocky Helmet = DOBLE daño al atacante
- NUNCA uses movimientos de recoil contra Pokémon con Rocky Helmet si tu Pokémon está a menos del 50% de HP

COMMANDER (Tatsugiri + Dondozo):
- Cuando Tatsugiri entra en campo con Dondozo activo, Tatsugiri desaparece DENTRO de Dondozo
- Tatsugiri con Commander NO puede ser atacado directamente mientras está dentro de Dondozo
- Dondozo recibe +2 en TODOS sus stats (Atk, Def, SpA, SpD, Spe)
- Para contrarrestar Commander: elimina a Dondozo, no a Tatsugiri

Habilidades críticas:
- Armor Tail / Queenly Majesty: BLOQUEAN todos los movimientos de prioridad del rival
- Clear Amulet: previene TODAS las bajadas de stats causadas por el rival
- Sand Rush: dobla velocidad en tormenta de arena
- Swift Swim: dobla velocidad bajo lluvia
- Chlorophyll: dobla velocidad bajo sol
- Intimidate: baja el Atk de los rivales al entrar en campo
- Beads of Ruin / Sword of Ruin: bajan stats de todos excepto el usuario

INSTRUCCIÓN CRÍTICA: Responde SIEMPRE con EXACTAMENTE este formato:
PREDICT: [qué movimientos hará probablemente el rival este turno, incluyendo posibles teras]
ACCION_P1: [nombre_movimiento_sin_espacios] [rival1|rival2] [tera] O switch:[nombre_pokemon]
ACCION_P2: [nombre_movimiento_sin_espacios] [rival1|rival2] [tera] O switch:[nombre_pokemon]
RAZONAMIENTO: [análisis incluyendo SIEMPRE los porcentajes de daño estimado para justificar cada decisión]

REGLAS ABSOLUTAS QUE NUNCA PUEDES VIOLAR:
1. Si el prompt muestra ADVERTENCIAS ACTIVAS, DEBES responderlas explícitamente en el RAZONAMIENTO
2. Si una advertencia dice "NO puede ser atacado", NUNCA uses ese Pokémon como objetivo
3. Si una advertencia dice "PELIGRO DE KO PROPIO" con Rocky Helmet, NUNCA uses ese movimiento de recoil
4. SOLO usa movimientos que aparezcan en la lista "Disponibles" de cada Pokémon — NUNCA inventes movimientos
5. SOLO usa switches a Pokémon que aparezcan en "MI BANCO" con su COMANDO EXACTO — NUNCA uses el nombre de un Pokémon que no esté listado en MI BANCO, aunque aparezca en el OTS del equipo. En VGC solo 4 de 6 Pokémon son seleccionados — los otros 2 NO existen en este combate
6. Si el rival tiene Dondozo + Tatsugiri y Tatsugiri está en campo, Tatsugiri NO puede ser atacado. Ataca a Dondozo
7. Antes de usar un movimiento de estado (Spore, Toxic, Will-O-Wisp) considera si el rival puede teracristalizar para inmunizarse

Para teracristalizar añade "tera" al final de la acción: ACCION_P1: glaciallance rival1 tera
Solo puedes teracristalizar si el Pokémon muestra [Tera disponible] en su estado. Una vez usado no puede repetirse.
Para Mega Evolucionar (solo en formato Champions) añade "mega" al final: ACCION_P1: bodyslam rival1 mega
Solo puedes mega evolucionar si el Pokémon lleva su Mega Stone. Solo un Pokémon puede mega evolucionar por combate.

Si solo hay 1 Pokémon activo en tu lado, omite ACCION_P2.
ACCION_P1 es SOLO para el Pokémon marcado como [P1]. ACCION_P2 es SOLO para el marcado como [P2].
SOLO usa movimientos que aparezcan en la lista "Disponibles" del Pokémon correspondiente.
Usa el nombre del movimiento en inglés sin espacios ni guiones.
Si un Pokémon está [BLOQUEADO en: X], solo puede usar ese movimiento o hacer switch.
Si un Pokémon está dormido, no puede atacar — omite su ACCION completamente (no escribas nada para ese Pokémon).
Si solo hay 1 Pokémon activo en tu lado (o el segundo está bajo Commander y no puede actuar), omite ACCION_P2 completamente — NO escribas "ACCION_P2: pass" ni "ACCION_P2: None" ni ningún texto explicativo.

Para el predict considera:
- Si el rival tiene un Pokémon a baja vida, probablemente protegerá o cambiará
- Si el rival puede hacer KO a uno de tus Pokémon, probablemente atacará
- Si el rival tiene Tailwind o Trick Room a punto de expirar, probablemente intentará renovarlo
- Si el rival tiene un Pokémon con Choice Item, está bloqueado en el último movimiento usado
- SIEMPRE considera si el rival podría teracristalizar — el tipo tera es visible en el open team sheet
- TeraBlast es un movimiento que CAMBIA DE TIPO según el tipo tera del Pokémon que lo usa.

Para teampreview:
SELECCION: [num] [num] [num] [num]
APERTURA: [num] [num]
RAZONAMIENTO: [2-3 frases de análisis]
"""


def formatear_pokemon_activo(pokemon, movimientos_disponibles=None, turno_actual=0, turno_entrada=None, can_tera=False):
    if pokemon is None:
        return "Vacío"
    nombre = pokemon.species
    hp = f"{pokemon.current_hp_fraction*100:.0f}%"
    tipo1 = pokemon.type_1.name if pokemon.type_1 else ""
    tipo2 = f"/{pokemon.type_2.name}" if pokemon.type_2 else ""
    estado = f" [{pokemon.status.name}]" if pokemon.status else ""
    boosts = [f"{s}:{'+' if v>0 else ''}{v}" for s, v in pokemon.boosts.items() if v != 0]
    boosts_str = f" Boosts:[{', '.join(boosts)}]" if boosts else ""
    habilidad = f" Hab:{pokemon.ability}" if pokemon.ability else ""
    if hasattr(pokemon, 'item') and pokemon.item:
        objeto = f" Obj:{pokemon.item}"
    elif hasattr(pokemon, 'end_item') and pokemon.end_item:
        objeto = f" Obj:PERDIDO(era {pokemon.end_item}) [Knock Off sin bonus]"
    else:
        objeto = ""

    # Determinar si es primer turno usando nuestro rastreo
    es_primer_turno = turno_entrada is not None and turno_actual == turno_entrada
    primer_turno = " [PRIMER TURNO EN CAMPO - Fake Out disponible]" if es_primer_turno else " [NO es primer turno - Fake Out fallará]"

    tera = ""
    if hasattr(pokemon, 'tera_type') and pokemon.tera_type:
        if hasattr(pokemon, 'terastallized') and pokemon.terastallized:
            tera = f" [TERACRISTALIZADO tipo {pokemon.tera_type.name}]"
        elif can_tera:
            tera = f" [Tera disponible: {pokemon.tera_type.name}]"
        else:
            tera = f" [Tera NO disponible - ya usada este combate]"

    stats_str = ""
    if hasattr(pokemon, 'stats') and pokemon.stats:
        spe = pokemon.stats.get('spe', '?')
        atk = pokemon.stats.get('atk', '?')
        spa = pokemon.stats.get('spa', '?')
        stats_str = f" Stats[Vel:{spe} Atk:{atk} SpA:{spa}]"
    elif hasattr(pokemon, 'base_stats') and pokemon.base_stats:
        spe = pokemon.base_stats.get('spe', '?')
        stats_str = f" Stats[Vel base:{spe}]"

    movs_str = ""
    if movimientos_disponibles:
        movs_str = f"\n    Disponibles: {', '.join(m.id for m in movimientos_disponibles)}"
    return f"{nombre} HP:{hp} Tipo:{tipo1}{tipo2}{estado}{boosts_str}{habilidad}{objeto}{primer_turno}{tera}{stats_str}{movs_str}"


def formatear_modificadores(battle):
    mods = []
    try:
        if battle.weather:
            weather = battle.weather
            if isinstance(weather, dict):
                for w in weather:
                    if hasattr(w, 'name') and w.name != "NONE":
                        mods.append(f"Clima: {w.name}")
            elif hasattr(weather, 'name') and weather.name != "NONE":
                mods.append(f"Clima: {weather.name}")
    except Exception:
        pass

    if Field.TRICK_ROOM in battle.fields:
        mods.append("TRICK ROOM activo")

    # Terrenos con sus efectos completos
    terrenos = {
        "ELECTRIC_TERRAIN": "Electric Terrain: potencia movimientos Eléctricos x1.3, bloquea movimientos de sueño, activa Quark Drive y Hadron Engine",
        "GRASSY_TERRAIN": "Grassy Terrain: restaura 1/16 HP cada turno a Pokémon en tierra, potencia movimientos Planta x1.3, reduce daño de Earthquake/Bulldoze/Magnitude a la mitad, activa Grassy Surge",
        "MISTY_TERRAIN": "Misty Terrain: bloquea todos los movimientos de estado (veneno, parálisis, sueño, quemadura, confusión), reduce daño de movimientos Dragón a la mitad",
        "PSYCHIC_TERRAIN": "Psychic Terrain: potencia movimientos Psíquicos x1.3, bloquea todos los movimientos de prioridad (Fake Out, Extreme Speed, Aqua Jet, etc.)",
    }
    for field in battle.fields:
        nombre = field.name if hasattr(field, 'name') else str(field)
        if nombre in terrenos:
            mods.append(terrenos[nombre])
        elif nombre not in ("TRICK_ROOM",):
            mods.append(f"Campo: {nombre}")

    if SideCondition.TAILWIND in battle.side_conditions:
        mods.append("Tailwind PROPIO activo")
    if SideCondition.TAILWIND in battle.opponent_side_conditions:
        mods.append("Tailwind RIVAL activo")
    if SideCondition.REFLECT in battle.side_conditions:
        mods.append("Reflect PROPIO")
    if SideCondition.LIGHT_SCREEN in battle.side_conditions:
        mods.append("Light Screen PROPIO")
    if SideCondition.REFLECT in battle.opponent_side_conditions:
        mods.append("Reflect RIVAL")
    if SideCondition.LIGHT_SCREEN in battle.opponent_side_conditions:
        mods.append("Light Screen RIVAL")

    return ", ".join(mods) if mods else "Ninguno"


def inferir_bulk_rival(battle, ev_defensa_rival):
    """
    Analiza el log del combate para detectar si un rival aguantó más de lo esperado
    y ajusta el multiplicador defensivo estimado.
    Retorna el diccionario ev_defensa_rival actualizado.
    """
    if not hasattr(battle, 'observations') or not battle.observations:
        return ev_defensa_rival

    # Buscar eventos de daño en los últimos turnos
    for turno_num in sorted(battle.observations.keys()):
        obs = battle.observations[turno_num]
        if not obs.events:
            continue
        for evento in obs.events:
            # Buscar eventos de tipo "-damage" que afecten a Pokémon rivales
            if len(evento) >= 4 and evento[1] == "-damage":
                target = evento[2]  # e.g. "p1a: Lickilicky"
                condition = evento[3]  # e.g. "250/350"
                # Solo nos interesan los rivales (p1 si somos p2, o viceversa)
                try:
                    if "/" in condition:
                        hp_actual, hp_max = condition.split("/")[:2]
                        hp_max = int(hp_max.split()[0])  # quitar status como "brn"
                        hp_actual = int(hp_actual)
                        # No tenemos el daño recibido directamente aquí, 
                        # pero podemos registrar el HP actual para comparar con cálculos
                except Exception:
                    pass
    return ev_defensa_rival


def construir_prompt_teampreview(battle, es_custom=False, ots_rival=None):
    equipo_propio = list(battle.team.values())
    equipo_rival = list(battle.opponent_team.values())

    prompt = "=== TEAMPREVIEW ===\n\nMI EQUIPO:\n"
    for i, p in enumerate(equipo_propio, 1):
        movs = list(p.moves.keys()) if p.moves else []
        item = p.item if hasattr(p, 'item') and p.item else "?"
        habilidad = p.ability if p.ability else "?"
        tipo = p.type_1.name if p.type_1 else ""
        if p.type_2:
            tipo += f"/{p.type_2.name}"
        tera = f" | Tera: {p.tera_type.name}" if hasattr(p, 'tera_type') and p.tera_type else ""
        prompt += f"{i}. {p.species} | {tipo} | Obj: {item} | Hab: {habilidad}{tera}"
        if movs:
            prompt += f" | Movs: {', '.join(movs)}"
        prompt += "\n"

    prompt += "\nEQUIPO RIVAL:\n"
    if ots_rival:
        for i, m in enumerate(ots_rival, 1):
            movs_str = f" | Movs: {', '.join(m.moves)}" if m.moves else ""
            item_str = f" | Obj: {m.item}" if m.item else ""
            ability_str = f" | Hab: {m.ability}" if m.ability else ""
            prompt += f"{i}. {m.nickname}{item_str}{ability_str}{movs_str}\n"
    else:
        for i, p in enumerate(equipo_rival, 1):
            item = p.item if hasattr(p, 'item') and p.item else "?"
            habilidad = p.ability if p.ability else "?"
            tipo = p.type_1.name if p.type_1 else ""
            if p.type_2:
                tipo += f"/{p.type_2.name}"
            movs = list(p.moves.keys()) if p.moves else []
            tera = f" | Tera: {p.tera_type.name}" if hasattr(p, 'tera_type') and p.tera_type else ""
            prompt += f"{i}. {p.species} | {tipo} | Obj: {item} | Hab: {habilidad}{tera}"
            if movs:
                prompt += f" | Movs: {', '.join(movs)}"
            prompt += "\n"

    if es_custom:
        prompt += "\nFormato: Doubles Custom Game. Se usan los 6 Pokémon. Solo elige los 2 mejores para ABRIR según el equipo rival. Considera sinergia, velocidad, amenazas inmediatas y type coverage."
        prompt += "\nResponde con APERTURA: [num] [num] y RAZONAMIENTO: [análisis]"
    else:
        nombres_str = " | ".join(f"{i}={p.species}" for i, p in enumerate(equipo_propio, 1))
        prompt += f"NUMEROS: {nombres_str}"
        prompt += "Identifica el core rival, elige los 4 mejores y la mejor apertura de 2. En SELECCION y APERTURA usa los numeros de arriba."
    return prompt


def construir_prompt_turno(battle, historial, turno_entrada=None, ots_rival=None, registro_rival=None, ultimo_protect=None, vel_minima_rival=None):
    activos_propios = [p for p in battle.active_pokemon if p is not None]
    activos_rivales = [p for p in battle.opponent_active_pokemon if p is not None]
    # Usar available_switches como fuente de verdad del banco — evita duplicados
    # y garantiza que solo se muestren Pokémon realmente disponibles para switch
    switches_disponibles = battle.available_switches or []
    if switches_disponibles and isinstance(switches_disponibles[0], list):
        switches_disponibles = [p for slot in switches_disponibles for p in slot if p is not None]
    # Deduplicar por species
    vistos = set()
    banco_propio = []
    for p in switches_disponibles:
        if p.species not in vistos:
            vistos.add(p.species)
            banco_propio.append(p)
    # Si no hay switches disponibles, fallback a battle.team
    if not banco_propio:
        for p in battle.team.values():
            if not p.active and not p.fainted and p.species not in vistos:
                vistos.add(p.species)
                banco_propio.append(p)
    banco_rival = [p for p in battle.opponent_team.values() if not p.active and not p.fainted]

    # Detectar si algún Pokémon propio está bajo Commander (no puede actuar)
    # Commander solo aplica si el Dondozo aliado también está activo en campo
    dondozo_propio_activo = any(
        p.species.lower() == "dondozo" and p.active
        for p in battle.team.values() if p is not None
    )
    pokemon_pueden_actuar = []
    for i, p in enumerate(activos_propios, 1):
        tiene_commander = hasattr(p, 'ability') and p.ability and p.ability.lower() == "commander"
        if tiene_commander and dondozo_propio_activo:
            pass  # Tatsugiri bajo Commander activo no puede actuar
        else:
            pokemon_pueden_actuar.append((i, p))

    prompt = f"=== TURNO {battle.turn} ===\n\n"
    prompt += f"Pokémon activos en mi lado: {len(pokemon_pueden_actuar)} (pueden actuar)\n\n"

    prompt += "MIS POKÉMON EN CAMPO:\n"
    for i, p in enumerate(activos_propios, 1):
        movs = battle.available_moves[i-1] if battle.available_moves and i-1 < len(battle.available_moves) else []
        entrada = turno_entrada.get(p.species) if turno_entrada else None
        inmunidades = []
        if p.type_1 and p.type_1.name == "NORMAL" or (p.type_2 and p.type_2.name == "NORMAL"):
            inmunidades.append("inmune a Fantasma")
        if p.type_1 and p.type_1.name == "GHOST" or (p.type_2 and p.type_2.name == "GHOST"):
            inmunidades.append("inmune a Normal y Lucha")
        if p.type_1 and p.type_1.name == "FLYING" or (p.type_2 and p.type_2.name == "FLYING"):
            inmunidades.append("inmune a Tierra")
        if p.type_1 and p.type_1.name == "GROUND" or (p.type_2 and p.type_2.name == "GROUND"):
            inmunidades.append("inmune a Eléctrico")
        if p.type_1 and p.type_1.name == "STEEL" or (p.type_2 and p.type_2.name == "STEEL"):
            inmunidades.append("inmune a Veneno")
        if p.type_1 and p.type_1.name == "DARK" or (p.type_2 and p.type_2.name == "DARK"):
            inmunidades.append("inmune a Psíquico y bloquea Prankster")
        if p.type_1 and p.type_1.name == "FAIRY" or (p.type_2 and p.type_2.name == "FAIRY"):
            inmunidades.append("inmune a Dragón")
        inmun_str = f" [INMUNE: {', '.join(inmunidades)}]" if inmunidades else ""
        # Determinar si la tera está disponible para este Pokémon
        p_can_tera = any(hasattr(m, 'can_tera') and m.can_tera for m in movs) if movs else False
        prompt += f"[P{i} - usa ACCION_P{i}]: {formatear_pokemon_activo(p, movs, battle.turn, entrada, can_tera=p_can_tera)}{inmun_str}\n"

        # Cálculos de daño para movimientos ofensivos
        if movs and activos_rivales:
            calc_lines = []
            for m in movs:
                if m.base_power > 0:
                    for j, rival in enumerate(activos_rivales, 1):
                        result = calcular_daño_aproximado(p, m, rival, battle)
                        if result:
                            pct_min, pct_max, mult = result
                            efecto = ""
                            if mult >= 2:
                                efecto = " ⚡SÚPER EFECTIVO"
                            elif mult <= 0.5:
                                efecto = " ⬇️poco efectivo"
                            hp_actual_rival = round(rival.current_hp_fraction * 100)
                            ko_str = " ⚠️KO!" if pct_min >= hp_actual_rival else (" ⚠️KO posible" if pct_max >= hp_actual_rival else "")
                            # Nota especial para movimientos de ráfaga variable
                            mov_id_lower = m.id.lower()
                            nota_rafaga = ""
                            if mov_id_lower in ("bulletseed", "rockblast", "pinmissile",
                                                "populationbomb", "tailslap", "spikecannon",
                                                "furyattack", "furyswipes", "bonerush"):
                                nota_rafaga = " (ráfaga 2-5 hits, daño mostrado es promedio ~3 hits)"
                            elif mov_id_lower == "surgingstrikes":
                                nota_rafaga = " (3 hits fijos, siempre crítico)"
                            elif mov_id_lower in ("wickedblow", "glaciallance"):
                                nota_rafaga = " (siempre crítico)"
                            calc_lines.append(
                                f"      {m.id} → R{j}(HP:{hp_actual_rival}%): daño {pct_min}-{pct_max}%{efecto}{ko_str}{nota_rafaga}"
                            )
            if calc_lines:
                prompt += "    Daño estimado (% HP rival, asume EVs estándar si rival):\n"
                for line in calc_lines:
                    prompt += line + "\n"

    prompt += "\nPOKÉMON RIVALES EN CAMPO:\n"
    for i, p in enumerate(activos_rivales, 1):
        # Calcular inmunidades relevantes
        inmunidades = []
        if p.type_1 and p.type_1.name == "NORMAL" or (p.type_2 and p.type_2.name == "NORMAL"):
            inmunidades.append("inmune a Fantasma")
        if p.type_1 and p.type_1.name == "GHOST" or (p.type_2 and p.type_2.name == "GHOST"):
            inmunidades.append("inmune a Normal y Lucha")
        if p.type_1 and p.type_1.name == "FLYING" or (p.type_2 and p.type_2.name == "FLYING"):
            inmunidades.append("inmune a Tierra")
        if p.type_1 and p.type_1.name == "GROUND" or (p.type_2 and p.type_2.name == "GROUND"):
            inmunidades.append("inmune a Eléctrico")
        if p.type_1 and p.type_1.name == "STEEL" or (p.type_2 and p.type_2.name == "STEEL"):
            inmunidades.append("inmune a Veneno")
        if p.type_1 and p.type_1.name == "DARK" or (p.type_2 and p.type_2.name == "DARK"):
            inmunidades.append("inmune a Psíquico y bloquea Prankster")
        if p.type_1 and p.type_1.name == "FAIRY" or (p.type_2 and p.type_2.name == "FAIRY"):
            inmunidades.append("inmune a Dragón")
        inmun_str = f" [INMUNE: {', '.join(inmunidades)}]" if inmunidades else ""
        prompt += f"[R{i} - target rival{i}]: {formatear_pokemon_activo(p, None, battle.turn, None)}{inmun_str}\n"
        # Mostrar tipo tera si está disponible y no ha teracristalizado aún
        if hasattr(p, 'tera_type') and p.tera_type and not (hasattr(p, 'terastallized') and p.terastallized):
            prompt += f"    ⚠️ Puede teracristalizar a: {p.tera_type.name} (cambia tipos e inmunidades)\n"
        # Si tenemos stats reales del rival (del open team sheet), mostrarlos
        if hasattr(p, 'stats') and p.stats:
            def_ = p.stats.get('def', None)
            spd = p.stats.get('spd', None)
            hp = p.stats.get('hp', None)
            if def_ or spd or hp:
                stats_str = []
                if hp: stats_str.append(f"HP:{hp}")
                if def_: stats_str.append(f"Def:{def_}")
                if spd: stats_str.append(f"SpD:{spd}")
                prompt += f"    Stats reales: {' '.join(stats_str)} — usa estos para calcular daño recibido\n"

        # Calcular daño que puede hacer este rival a mis Pokémon activos
        # Usar movimientos conocidos (del OTS o los observados)
        movs_rival = list(p.moves.values()) if p.moves else []
        # Si hay OTS, usar esos movimientos que son más completos
        if ots_rival:
            for ots_mon in ots_rival:
                if ots_mon.nickname and ots_mon.nickname.lower().replace('-','').replace(' ','') == p.species.lower().replace('-','').replace(' ',''):
                    if ots_mon.moves:
                        from poke_env.battle import Move
                        movs_rival_ots = []
                        for nombre_mov in ots_mon.moves:
                            try:
                                mov = Move(nombre_mov.lower().replace(' ','').replace('-',''), gen=9)
                                movs_rival_ots.append(mov)
                            except Exception:
                                pass
                        if movs_rival_ots:
                            movs_rival = movs_rival_ots
                    break

        if movs_rival and activos_propios:
            calc_entrante = []
            for m in movs_rival:
                if not hasattr(m, 'base_power') or m.base_power <= 0:
                    continue
                for j, propio in enumerate(activos_propios, 1):
                    result = calcular_daño_aproximado(p, m, propio, battle)
                    if result:
                        pct_min, pct_max, mult = result
                        efecto = ""
                        if mult >= 2:
                            efecto = " ⚡SÚPER EFECTIVO"
                        elif mult <= 0.5:
                            efecto = " ⬇️poco efectivo"
                        ko_str = " ⚠️KO POSIBLE" if pct_min >= 100 else (" ⚠️KO SI CRITICO" if pct_max >= 100 else "")
                        calc_entrante.append(
                            f"      {m.id} → P{j}: {pct_min}-{pct_max}%{efecto}{ko_str}"
                        )
            if calc_entrante:
                prompt += "    Daño que puede hacer a mis Pokémon:\n"
                for line in calc_entrante:
                    prompt += line + "\n"

    if banco_propio:
        prompt += f"\nMI BANCO (disponibles para switch):\n"
        nombres_banco = set()
        for p in banco_propio:
            hp = f"{p.current_hp_fraction*100:.0f}%"
            estado = f" [{p.status.name}]" if p.status else ""
            habilidad = f" Hab:{p.ability}" if p.ability else ""
            objeto = f" Obj:{p.item}" if hasattr(p, 'item') and p.item else ""
            nombre_switch_cmd = p.species.lower().replace('-','').replace(' ','')
            nombres_banco.add(nombre_switch_cmd)
            prompt += f"  - {p.species} HP:{hp}{estado}{habilidad}{objeto} COMANDO: switch:{nombre_switch_cmd}\n"

        # Pokémon del equipo completo que NO están disponibles
        no_disponibles = []
        for p in battle.team.values():
            nombre_cmd = p.species.lower().replace('-','').replace(' ','')
            activo = p.active
            fainted = p.fainted
            if not activo and not fainted and nombre_cmd not in nombres_banco:
                no_disponibles.append(p.species)
        if no_disponibles:
            prompt += f"  🚨 ESTOS POKÉMON NO FUERON SELECCIONADOS Y NO PUEDES USARLOS: {', '.join(no_disponibles)}\n"
        prompt += f"  IMPORTANTE: Solo puedes hacer switch a los Pokémon listados arriba con su COMANDO EXACTO.\n"
    if banco_rival:
        prompt += f"BANCO RIVAL (confirmados — ya aparecieron en combate):\n"
        for p in banco_rival:
            if not p.fainted:
                hp = f"{p.current_hp_fraction*100:.0f}%"
                estado = f" [{p.status.name}]" if p.status else ""
                movs = list(p.moves.keys()) if p.moves else []
                movs_str = f" Movs:[{', '.join(movs)}]" if movs else ""
                item = f" Obj:{p.item}" if p.item and p.item != "unknown_item" else ""
                ability = f" Hab:{p.ability}" if p.ability else ""
                prompt += f"  - {p.species} HP:{hp}{estado}{item}{ability}{movs_str}\n"

    # Pokémon del OTS que aún no han aparecido en campo
    ots_rival = ots_rival or []
    especies_vistas = {p.species.lower().replace('-','').replace(' ','')
                       for p in battle.opponent_team.values()}
    mons_no_vistos = [m for m in ots_rival
                      if m.nickname and
                      m.nickname.lower().replace('-','').replace(' ','') not in especies_vistas]
    if mons_no_vistos:
        prompt += f"BANCO RIVAL (posibles — en el OTS pero aún no confirmados en este combate):\n"
        prompt += f"  ⚠️ El rival eligió 4 de 6 Pokémon. Estos pueden o no estar seleccionados — no los des por confirmados hasta que aparezcan.\n"
        for m in mons_no_vistos:
            movs_str = f" Movs:[{', '.join(m.moves)}]" if m.moves else ""
            item_str = f" Obj:{m.item}" if m.item else ""
            ability_str = f" Hab:{m.ability}" if m.ability else ""
            prompt += f"  - {m.nickname}{item_str}{ability_str}{movs_str} (¿seleccionado?)\n"

    # Mostrar registro estructurado del rival si hay información relevante
    if registro_rival:
        lineas_registro = []
        for species, datos in registro_rival.items():
            partes = []
            movs = datos.get("movs", {})
            if movs:
                movs_str = ", ".join(f"{m}(x{n})" if n > 1 else m for m, n in movs.items())
                partes.append(f"usó: {movs_str}")
            protects = datos.get("protects", 0)
            if protects > 0:
                partes.append(f"protegió {protects}x")
            if datos.get("tera"):
                partes.append("ya teracristalizó")
            obj = datos.get("objeto_revelado")
            if obj:
                partes.append(f"objeto revelado: {obj}")
            if partes:
                lineas_registro.append(f"  {species}: {' | '.join(partes)}")
        if lineas_registro:
            prompt += f"\nREGISTRO DEL RIVAL (movimientos observados):\n"
            for l in lineas_registro:
                prompt += l + "\n"

    prompt += f"\nMODIFICADORES: {formatear_modificadores(battle)}\n"

    # Evaluación de posición
    try:
        # HP total de cada lado (activos + banco)
        hp_propio = sum(p.current_hp_fraction for p in battle.team.values() if not p.fainted)
        n_propios = sum(1 for p in battle.team.values() if not p.fainted)
        hp_rival = sum(p.current_hp_fraction for p in battle.opponent_team.values() if not p.fainted)
        n_rivales = sum(1 for p in battle.opponent_team.values() if not p.fainted)

        ventaja = "IGUALADO"
        if n_propios > n_rivales + 1:
            ventaja = "VENTAJA NUMÉRICA CLARA — sé agresivo, no protejas sin razón"
        elif n_propios < n_rivales - 1:
            ventaja = "DESVENTAJA NUMÉRICA — juega con más cuidado"
        elif n_propios > n_rivales:
            ventaja = "LIGERA VENTAJA — presiona"
        elif n_propios < n_rivales:
            ventaja = "LIGERA DESVENTAJA"
        elif hp_propio > hp_rival * 1.3:
            ventaja = "VENTAJA EN HP"
        elif hp_propio < hp_rival * 0.7:
            ventaja = "DESVENTAJA EN HP"

        prompt += f"\nEVALUACIÓN: Mis Pokémon vivos: {n_propios} | Rivales vivos: {n_rivales} | Estado: {ventaja}\n"

        # Análisis de victoria — calcular si puede ganar y cómo
        try:
            rivales_vivos = [p for p in battle.opponent_team.values() if not p.fainted]
            propios_vivos = [p for p in battle.team.values() if not p.fainted]

            # Calcular daño máximo que pueden hacer los Pokémon propios activos
            amenazas_rival = []
            for rival in rivales_vivos:
                hp_pct = round(rival.current_hp_fraction * 100)
                amenazas_rival.append(f"{rival.species}(HP:{hp_pct}%)")

            # Calcular si algún activo propio puede KO a algún rival activo
            ko_posibles = []
            for i, p in enumerate(activos_propios, 1):
                movs = battle.available_moves[i-1] if battle.available_moves and i-1 < len(battle.available_moves) else []
                for m in movs:
                    if m.base_power <= 0:
                        continue
                    for j, rival in enumerate(activos_rivales, 1):
                        result = calcular_daño_aproximado(p, m, rival, battle)
                        if result:
                            pct_min, pct_max, _ = result
                            hp_rival_actual = round(rival.current_hp_fraction * 100)
                            if pct_min >= hp_rival_actual:
                                ko_posibles.append(f"P{i} puede KO R{j}({rival.species}) con {m.id}")

            # Evaluar si la tera cambiaría el resultado
            tera_recomendaciones = []
            for i, p in enumerate(activos_propios, 1):
                movs = battle.available_moves[i-1] if battle.available_moves and i-1 < len(battle.available_moves) else []
                p_can_tera = any(hasattr(m, 'can_tera') and m.can_tera for m in movs)
                if not p_can_tera:
                    continue
                tera_type = p.tera_type if hasattr(p, 'tera_type') and p.tera_type else None
                if not tera_type:
                    continue
                # Comprobar si algún rival activo amenaza con KO a este Pokémon
                for j, rival in enumerate(activos_rivales, 1):
                    movs_rival = list(rival.moves.values()) if rival.moves else []
                    for mr in movs_rival:
                        if not hasattr(mr, 'base_power') or mr.base_power <= 0:
                            continue
                        result = calcular_daño_aproximado(rival, mr, p, battle)
                        if result:
                            pct_min, pct_max, mult = result
                            hp_propio_actual = round(p.current_hp_fraction * 100)
                            # Si el rival puede KO y la tera cambiaría la efectividad
                            if pct_max >= hp_propio_actual and mult >= 2:
                                # Verificar si la tera eliminaría esa debilidad
                                try:
                                    mult_con_tera = mr.type.damage_multiplier(
                                        tera_type, None, type_chart=TYPE_CHART
                                    )
                                    if mult_con_tera < mult:
                                        tera_recomendaciones.append(
                                            f"⚡TERA RECOMENDADA: P{i} {p.species} puede teracristalizar a {tera_type.name} "
                                            f"para reducir {mr.id} de R{j} de {mult}x a {mult_con_tera}x y sobrevivir"
                                        )
                                except Exception:
                                    pass
                # Comprobar si la tera permitiría un KO que sin tera no sería posible
                for m in movs:
                    if m.base_power <= 0:
                        continue
                    for j, rival in enumerate(activos_rivales, 1):
                        result_normal = calcular_daño_aproximado(p, m, rival, battle)
                        if result_normal:
                            pct_min_n, pct_max_n, _ = result_normal
                            hp_rival_actual = round(rival.current_hp_fraction * 100)
                            # Sin tera no hace KO pero con tera (STAB) podría
                            if pct_max_n < hp_rival_actual and tera_type and m.type == tera_type:
                                pct_con_tera_max = round(pct_max_n * 1.5)  # STAB bonus
                                if pct_con_tera_max >= hp_rival_actual:
                                    tera_recomendaciones.append(
                                        f"⚡TERA OFENSIVA: P{i} {p.species} con Tera {tera_type.name} "
                                        f"podría KO a R{j}({rival.species}) con {m.id} "
                                        f"({pct_min_n}-{pct_max_n}% → ~{pct_con_tera_max}% con STAB tera)"
                                    )

            prompt += f"\nANÁLISIS DE VICTORIA:\n"
            prompt += f"  Rivales que debo derrotar: {', '.join(amenazas_rival)}\n"
            if ko_posibles:
                prompt += f"  KOs posibles ESTE TURNO: {' | '.join(ko_posibles)}\n"
            else:
                prompt += f"  No hay KOs garantizados este turno — considera desgaste o switches\n"
            if tera_recomendaciones:
                for rec in tera_recomendaciones:
                    prompt += f"  {rec}\n"

            # Evaluar si la situación es ganable
            if n_propios > 0 and n_rivales > 0:
                hp_medio_propio = hp_propio / n_propios
                hp_medio_rival = hp_rival / n_rivales
                if n_propios >= n_rivales and hp_medio_propio >= hp_medio_rival * 0.8:
                    prompt += f"  POSICIÓN: Favorable — busca KOs y no desperdicies turnos con Protect innecesario\n"
                elif n_propios < n_rivales or hp_medio_propio < hp_medio_rival * 0.5:
                    prompt += f"  POSICIÓN: Difícil — necesitas una jugada de alto impacto, no juegues conservador\n"
                else:
                    prompt += f"  POSICIÓN: Equilibrada — cada intercambio cuenta, elige con cuidado\n"
        except Exception:
            pass
    except Exception:
        pass

    try:
        tailwind_propio = any("tailwind" in str(e).lower() for e in (battle.side_conditions or {}).keys()) if hasattr(battle, 'side_conditions') else False
        tailwind_rival = any("tailwind" in str(e).lower() for e in (battle.opponent_side_conditions or {}).keys()) if hasattr(battle, 'opponent_side_conditions') else False
        trick_room = any("trickroom" in str(e).lower() for e in (battle.fields or {}).keys()) if hasattr(battle, 'fields') else False

        def aplicar_boost_vel(vel, boost):
            """Aplica boost/bajada de velocidad según la tabla de stats de Gen 9."""
            if boost > 0:
                return math.floor(vel * (2 + boost) / 2)
            elif boost < 0:
                return math.floor(vel * 2 / (2 - boost))
            return vel

        pokemon_velocidades = []
        for i, p in enumerate(activos_propios, 1):
            vel = None
            if hasattr(p, 'stats') and p.stats:
                vel = p.stats.get('spe')
            elif hasattr(p, 'base_stats') and p.base_stats:
                base = p.base_stats.get('spe', 50)
                vel = math.floor((2 * base + 31 + 63) * 50 / 100) + 5
            if vel:
                # Aplicar boosts de velocidad
                spe_boost = p.boosts.get('spe', 0) if hasattr(p, 'boosts') and p.boosts else 0
                vel = aplicar_boost_vel(vel, spe_boost)
                vel_final = vel * 2 if tailwind_propio else vel
                etiqueta = f"P{i}:{p.species}"
                if spe_boost != 0:
                    etiqueta += f"(Vel{'+' if spe_boost > 0 else ''}{spe_boost})"
                pokemon_velocidades.append((etiqueta, vel_final, True))
        for i, p in enumerate(activos_rivales, 1):
            vel = None
            if hasattr(p, 'stats') and p.stats:
                vel = p.stats.get('spe')
            elif hasattr(p, 'base_stats') and p.base_stats:
                base = p.base_stats.get('spe', 50)
                vel = math.floor((2 * base + 31 + 63) * 50 / 100) + 5
            if vel:
                # Usar velocidad inferida si es mayor que la calculada
                vel_inferida = (vel_minima_rival or {}).get(p.species, 0)
                nota_inferida = ""
                if vel_inferida > vel:
                    vel = vel_inferida
                    nota_inferida = "(vel inferida por observación)"
                # Aplicar boosts de velocidad del rival
                spe_boost = p.boosts.get('spe', 0) if hasattr(p, 'boosts') and p.boosts else 0
                vel = aplicar_boost_vel(vel, spe_boost)
                scarf = hasattr(p, 'item') and p.item and p.item.lower() == "choicescarf"
                vel_final = vel * 2 if tailwind_rival else vel
                if scarf:
                    vel_final = math.floor(vel_final * 1.5)
                etiqueta = f"R{i}:{p.species}"
                if scarf:
                    etiqueta += "(Scarf)"
                if spe_boost != 0:
                    etiqueta += f"(Vel{'+' if spe_boost > 0 else ''}{spe_boost})"
                if nota_inferida:
                    etiqueta += "⚠️"
                pokemon_velocidades.append((etiqueta, vel_final, False))

        if pokemon_velocidades:
            if trick_room:
                pokemon_velocidades.sort(key=lambda x: x[1])
                prompt += f"ORDEN DE ACTUACIÓN (Trick Room activo - más lento va primero):\n"
            else:
                pokemon_velocidades.sort(key=lambda x: -x[1])
                prompt += f"ORDEN DE ACTUACIÓN (velocidades reales con boosts aplicados):\n"
            for nombre, vel, es_propio in pokemon_velocidades:
                tw = "(x2 Tailwind)" if (es_propio and tailwind_propio) or (not es_propio and tailwind_rival) else ""
                prompt += f"  {nombre} Vel:{vel}{tw}\n"
            prompt += f"  ⚠️ Extreme Speed (+2), Aqua Jet/Bullet Punch/Sucker Punch (+1), Prankster estados (+1) actúan ANTES del orden de velocidad\n"
    except Exception:
        pass


    HABILIDADES_ANTI_PRIORIDAD = {
        "armortail", "queenlymajesty", "dazzling", "abilitybullet"
    }
    # Objetos que previenen bajadas de stats
    OBJETOS_ANTI_BAJADA = {
        "clearamulet"
    }
    # Habilidades que previenen bajadas de stats
    HABILIDADES_ANTI_BAJADA = {
        "whitesmoke", "clearbody", "fullmetalbody", "mirrorarmor"
    }

    # Advertencias activas calculadas en código
    advertencias = []

    # Advertencia de Protect consecutivo — no puede usarse dos turnos seguidos
    if ultimo_protect:
        for i, p in enumerate(activos_propios, 1):
            turno_protect = ultimo_protect.get(p.species)
            if turno_protect is not None and turno_protect == battle.turn - 1:
                advertencias.append(
                    f"🚨 REGLA ABSOLUTA: P{i} {p.species} usó Protect/Detect el turno anterior. "
                    f"NO puede volver a usarlo este turno — fallará. Elige otro movimiento."
                )

    for p in activos_rivales:
        if p.ability and p.ability.lower() in HABILIDADES_ANTI_PRIORIDAD:
            advertencias.append(
                f"⚠️ {p.species} tiene {p.ability}: NINGÚN movimiento de prioridad funcionará "
                f"(Fake Out, Sucker Punch, Aqua Jet, Thunderclap, Extreme Speed, etc.)"
            )
        if (hasattr(p, 'item') and p.item and p.item.lower() in OBJETOS_ANTI_BAJADA) or \
           (p.ability and p.ability.lower() in HABILIDADES_ANTI_BAJADA):
            advertencias.append(
                f"⚠️ {p.species} tiene {p.item or p.ability}: movimientos que SOLO bajan stats "
                f"(Parting Shot, Snarl, Icy Wind) no tendrán efecto"
            )

    for p in activos_rivales:
        if (not p.item) and hasattr(p, 'end_item') and p.end_item:
            advertencias.append(
                f"⚠️ {p.species} ya no tiene objeto (tenía {p.end_item}) — "
                f"Knock Off hará daño normal sin el bonus del 50%"
            )

    dormidos_rival = [p for p in battle.opponent_team.values()
                     if p.status and p.status.name == "SLP" and not p.fainted]
    if dormidos_rival:
        advertencias.append(
            f"⚠️ SLEEP CLAUSE: {dormidos_rival[0].species} ya está dormido — "
            f"NO uses Spore ni Sleep Powder en otros rivales"
        )

    # Advertencia de Pokémon propio dormido
    for i, p in enumerate(activos_propios, 1):
        if p.status and p.status.name == "SLP":
            advertencias.append(
                f"⚠️ P{i} {p.species} está DORMIDO — no puede atacar este turno. "
                f"Actúa con el otro Pokémon de forma independiente"
            )

    # Advertencia de Choice Item bloqueado
    for i, p in enumerate(activos_propios, 1):
        if hasattr(p, 'item') and p.item and p.item.lower() in {"choiceband", "choicespecs", "choicescarf"}:
            if hasattr(p, 'moves') and p.moves:
                movs_usados = [m for m in p.moves.values() if hasattr(m, 'used') and m.used]
                # Verificar si está locked mirando los movimientos disponibles
                movs_disp = battle.available_moves[i-1] if battle.available_moves and i-1 < len(battle.available_moves) else []
                if len(movs_disp) == 1 and movs_disp[0].id != "struggle":
                    advertencias.append(
                        f"⚠️ P{i} {p.species} lleva {p.item} y está BLOQUEADO en: {movs_disp[0].id} — "
                        f"solo puede usar ese movimiento o hacer switch"
                    )

    # Advertencia de trapping (atrapado por movimiento)
    for i, p in enumerate(activos_propios, 1):
        if hasattr(p, 'effects') and p.effects:
            for effect in p.effects:
                if hasattr(effect, 'name') and 'trap' in effect.name.lower():
                    advertencias.append(
                        f"⚠️ P{i} {p.species} está ATRAPADO — no puede hacer switch"
                    )

    # Advertencia de Yawn pendiente
    for i, p in enumerate(activos_propios, 1):
        if hasattr(p, 'effects') and p.effects:
            for effect in p.effects:
                if hasattr(effect, 'name') and 'yawn' in effect.name.lower():
                    advertencias.append(
                        f"⚠️ P{i} {p.species} está bajo YAWN — se dormirá al final de este turno. "
                        f"Protect NO evita el sueño. La única forma de evitarlo es hacer switch ahora"
                    )

    # Advertencia de evasión alta del rival
    for p in activos_rivales:
        evasion = 0
        if hasattr(p, 'boosts') and p.boosts:
            evasion = p.boosts.get('evasion', 0)
        if evasion >= 2:
            precision_efectiva = int(100 * (3/(3+evasion)) * 100) // 100
            advertencias.append(
                f"⚠️ {p.species} tiene evasión +{evasion} (~{precision_efectiva}% precisión efectiva) — "
                f"considera spread moves (Earthquake, Rock Slide) o movimientos que no fallan"
            )

    # Advertencia de spread moves que dañan aliados en campo
    if len(activos_propios) > 1:
        for i, p in enumerate(activos_propios, 1):
            movs_disp = battle.available_moves[i-1] if battle.available_moves and i-1 < len(battle.available_moves) else []
            aliado_idx = 1 if i == 1 else 0
            if aliado_idx < len(activos_propios):
                aliado = activos_propios[aliado_idx]
                # Si el aliado tiene Commander activo, es invulnerable — no generar advertencia
                if hasattr(aliado, 'ability') and aliado.ability and aliado.ability.lower() == "commander":
                    continue
                for m in movs_disp:
                    if hasattr(m, 'target') and m.target and m.target.name in ("ALL_ADJACENT",):
                        try:
                            mult = m.type.damage_multiplier(aliado.type_1, aliado.type_2, type_chart=TYPE_CHART)
                            if mult > 0:
                                advertencias.append(
                                    f"⚠️ {m.id} de P{i} golpea también al aliado P{aliado_idx+1} {aliado.species} "
                                    f"({mult}x daño). NO uses este movimiento si el aliado está en campo"
                                )
                        except Exception:
                            pass

    # Advertencia de Commander propio activo
    for i, p in enumerate(activos_propios, 1):
        if hasattr(p, 'ability') and p.ability and p.ability.lower() == "commander":
            advertencias.append(
                f"ℹ️ P{i} {p.species} está dentro de tu Dondozo (Commander). "
                f"NO puede actuar — omite ACCION_P{i} completamente. "
                f"Earthquake y otros spread moves de Dondozo NO le afectan porque es invulnerable."
            )
    for p in activos_rivales:
        if p.ability and p.ability.lower() == "commander":
            advertencias.append(
                f"🚨 REGLA ABSOLUTA: {p.species} tiene Commander activo — está DENTRO de Dondozo y es COMPLETAMENTE INMUNE a ataques. "
                f"Cualquier ataque dirigido a {p.species} FALLARÁ. Ataca ÚNICAMENTE al Dondozo."
            )
    # Detectar si el rival tiene Dondozo en campo con boosts altos (Commander activo)
    for p in activos_rivales:
        if p.species.lower() == "dondozo" and hasattr(p, 'boosts') and p.boosts:
            total_boost = sum(v for v in p.boosts.values() if v > 0)
            if total_boost >= 6:
                advertencias.append(
                    f"🚨 Dondozo rival tiene Commander activo (boosts altos). "
                    f"Tatsugiri está DENTRO y es INVULNERABLE. Solo ataca a Dondozo."
                )
    # Detectar si el rival tiene Dondozo en campo Y Tatsugiri en el banco (Commander inminente)
    dondozo_activo = any(p.species.lower() == "dondozo" for p in activos_rivales)
    tatsugiri_en_banco = any(p.species.lower() == "tatsugiri" for p in battle.opponent_team.values()
                             if not p.active and not p.fainted)
    if dondozo_activo and tatsugiri_en_banco:
        advertencias.append(
            f"⚠️ AMENAZA INMINENTE: El rival tiene Dondozo en campo y Tatsugiri en el banco. "
            f"Si Tatsugiri entra, activará Commander y Dondozo tendrá +2 en TODOS los stats. "
            f"Prioridad: elimina a Dondozo ANTES de que Tatsugiri entre."
        )
    for p in activos_rivales:
        movs_rival_conocidos = list(p.moves.keys()) if p.moves else []
        # Buscar en OTS también
        if ots_rival:
            for ots_mon in ots_rival:
                if ots_mon.nickname and ots_mon.nickname.lower().replace('-','').replace(' ','') == p.species.lower().replace('-','').replace(' ',''):
                    if ots_mon.moves:
                        movs_rival_conocidos = [m.lower() for m in ots_mon.moves]
        if any("terablast" in m.lower() for m in movs_rival_conocidos):
            tera_tipo = p.tera_type.name if hasattr(p, 'tera_type') and p.tera_type else "desconocido"
            if not (hasattr(p, 'terastallized') and p.terastallized):
                advertencias.append(
                    f"⚠️ {p.species} tiene TeraBlast y puede teracristalizar a {tera_tipo}. "
                    f"Si tera, TeraBlast será de tipo {tera_tipo} — considera las nuevas resistencias e inmunidades antes de atacar"
                )

    # Advertencia de movimiento de estado contra Pokémon con tera que da inmunidad
    ESTADOS_TIPO_INMUNE = {
        "spore": "GRASS", "sleeppowder": "GRASS", "leechseed": "GRASS",
        "toxic": "POISON", "poisonpowder": "POISON",
        "thunderwave": "ELECTRIC",
        "willowisp": "FIRE",
    }
    for i, p in enumerate(activos_propios, 1):
        movs_disp = battle.available_moves[i-1] if battle.available_moves and i-1 < len(battle.available_moves) else []
        for m in movs_disp:
            tipo_inmune = ESTADOS_TIPO_INMUNE.get(m.id.lower())
            if tipo_inmune:
                for j, rival in enumerate(activos_rivales, 1):
                    if hasattr(rival, 'tera_type') and rival.tera_type and not (hasattr(rival, 'terastallized') and rival.terastallized):
                        if rival.tera_type.name == tipo_inmune:
                            advertencias.append(
                                f"⚠️ {m.id} de P{i} FALLARÁ si R{j} {rival.species} teracristaliza a {tipo_inmune} "
                                f"(inmune a {m.id}). ¿Tiene el rival incentivo para tera ahora?"
                            )

    # Advertencia de Rocky Helmet + movimiento de recoil
    MOVIMIENTOS_RECOIL = {"wavecrash", "doubleedge", "flareblitz", "bravebird", "headsmash",
                          "submission", "takedown", "volttackle", "woodhammer", "headcharge",
                          "highjumpkick", "jumpkick", "wildcharge"}
    for i, p in enumerate(activos_propios, 1):
        movs_disp = battle.available_moves[i-1] if battle.available_moves and i-1 < len(battle.available_moves) else []
        tiene_recoil = any(m.id.lower() in MOVIMIENTOS_RECOIL for m in movs_disp)
        if tiene_recoil:
            for rival in activos_rivales:
                if hasattr(rival, 'item') and rival.item and rival.item.lower() == "rockyhelmet":
                    hp_pct = p.current_hp_fraction * 100
                    advertencias.append(
                        f"⚠️ P{i} {p.species} ({hp_pct:.0f}% HP): movimiento de recoil contra "
                        f"{rival.species} (Rocky Helmet) = recoil del movimiento + 16.7% HP extra. "
                        f"{'MUY PELIGROSO — probablemente suicida' if hp_pct < 50 else 'Calcula si puedes aguantarlo'}"
                    )

    # Advertencia de Commander rival (Tatsugiri dentro de Dondozo)
    especies_rivales_activas = {p.species.lower() for p in activos_rivales}
    if 'dondozo' in especies_rivales_activas:
        for p in battle.opponent_team.values():
            if 'tatsugiri' in p.species.lower() and not p.fainted and not p.active:
                advertencias.append(
                    f"⚠️ COMMANDER INMINENTE: el rival tiene Dondozo en campo y Tatsugiri en el equipo. "
                    f"Si Tatsugiri entra, se activará Commander: Dondozo ganará +2 en TODOS sus stats y "
                    f"Tatsugiri quedará invulnerable dentro. Considera KO a Dondozo antes de que entre Tatsugiri."
                )
        if hasattr(p, 'boosts') and p.boosts:
            spa_boost = p.boosts.get('spa', 0)
            if spa_boost <= -2:
                mult = {-2: 56, -3: 43, -4: 33, -5: 27, -6: 25}.get(spa_boost, 25)
                advertencias.append(
                    f"⚠️ P{i} {p.species} tiene SpA {spa_boost} — sus ataques especiales hacen ~{mult}% del daño normal. "
                    f"Considera cambiar o usar movimientos físicos"
                )

    # Advertencia de speed ties
    for p_propio in activos_propios:
        vel_propia = None
        if hasattr(p_propio, 'stats') and p_propio.stats:
            vel_propia = p_propio.stats.get('spe')
        elif hasattr(p_propio, 'base_stats') and p_propio.base_stats:
            vel_propia = p_propio.base_stats.get('spe')
        if vel_propia is None:
            continue
        for p_rival in activos_rivales:
            vel_rival = None
            if hasattr(p_rival, 'base_stats') and p_rival.base_stats:
                vel_rival = p_rival.base_stats.get('spe')
            if vel_rival is None:
                continue
            if abs(vel_propia - vel_rival) <= max(3, vel_propia * 0.10):
                advertencias.append(
                    f"⚠️ SPEED TIE posible: {p_propio.species} (Vel:{vel_propia}) vs "
                    f"{p_rival.species} (Vel base:{vel_rival}) — el orden de ataque es impredecible (50/50)"
                )

    if advertencias:
        prompt += f"\n{'='*40}\nADVERTENCIAS ACTIVAS:\n"
        for adv in advertencias:
            prompt += f"{adv}\n"
        prompt += f"{'='*40}\n"
        prompt += f"\nÚLTIMOS TURNOS (razonamiento):\n"
        for entrada in historial[-4:]:
            prompt += f"  {entrada}\n"
        prompt += "\nIMPORTANTE: Si usaste Protect, Wide Guard, Quick Guard o Detect el turno anterior con el mismo Pokémon, NO puedes usarlo de nuevo este turno (fallará).\n"

    # Añadir log real de eventos de los últimos 3 turnos
    if hasattr(battle, 'observations') and battle.observations:
        turnos_recientes = sorted(battle.observations.keys())[-3:]
        if turnos_recientes:
            prompt += f"\nLOG REAL DEL COMBATE (últimos turnos):\n"
            for turno_num in turnos_recientes:
                obs = battle.observations[turno_num]
                if obs.events:
                    prompt += f"  Turno {turno_num}:\n"
                    for evento in obs.events:
                        if len(evento) > 1:
                            tipo = evento[1] if len(evento) > 1 else ""
                            # Filtrar solo eventos relevantes
                            if tipo in ("-damage", "-heal", "-boost", "-unboost",
                                       "move", "-weather", "-fieldstart", "-fieldend",
                                       "-sidestart", "-sideend", "-status", "-curestatus",
                                       "switch", "drag", "-ability", "-item", "-enditem",
                                       "faint", "-activate", "-terastallize",
                                       "-start", "-end", "cant"):
                                prompt += f"    {' | '.join(evento[1:])}\n"

    prompt += "\n¿Qué haces este turno?"
    return prompt


def parsear_respuesta_teampreview(respuesta, n_pokemon):
    seleccion = []
    apertura = []
    razonamiento = ""
    if not respuesta:
        seleccion = list(range(1, min(5, n_pokemon + 1)))
        return seleccion, seleccion[:2], razonamiento

    # Limpiar markdown
    respuesta_limpia = respuesta.replace("**", "").replace("*", "")

    for linea in respuesta_limpia.strip().split('\n'):
        linea = linea.strip()
        if not linea:
            continue
        linea_upper = linea.upper()
        if "RAZONAMIENTO:" in linea_upper:
            idx = linea_upper.index("RAZONAMIENTO:")
            razonamiento = linea[idx + len("RAZONAMIENTO:"):].strip()
        elif "SELECCION:" in linea_upper:
            idx = linea_upper.index("SELECCION:")
            parte = linea[idx + len("SELECCION:"):].strip()
            nums = [s for s in parte.replace(",", " ").split() if s.isdigit()]
            seleccion = [int(n) for n in nums if 1 <= int(n) <= n_pokemon]
        elif "APERTURA:" in linea_upper:
            idx = linea_upper.index("APERTURA:")
            parte = linea[idx + len("APERTURA:"):].strip()
            nums = [s for s in parte.replace(",", " ").split() if s.isdigit()]
            # Filtrar estrictamente por rango válido
            apertura = [int(n) for n in nums if 1 <= int(n) <= n_pokemon]

    # Fallbacks robustos
    if len(seleccion) < 4:
        seleccion = list(range(1, min(5, n_pokemon + 1)))
    # La apertura DEBE estar dentro de la selección y del rango válido
    apertura_valida = [n for n in apertura if n in seleccion]
    if len(apertura_valida) < 2:
        apertura_valida = seleccion[:2]

    print(f"  [Teampreview parseado] selección={seleccion[:4]} apertura={apertura_valida[:2]} n_pokemon={n_pokemon}")
    return seleccion[:4], apertura_valida[:2], razonamiento


def parsear_respuesta_turno(respuesta):
    razonamiento = ""
    accion_p1 = None
    accion_p2 = None
    predict = ""
    if not respuesta:
        return razonamiento, accion_p1, accion_p2, predict
    # Limpiar markdown bold/italic que Gemini a veces añade
    respuesta_limpia = respuesta.replace("**", "").replace("*", "")
    for linea in respuesta_limpia.strip().split('\n'):
        linea = linea.strip()
        if not linea:
            continue
        linea_upper = linea.upper()
        if "RAZONAMIENTO:" in linea_upper:
            idx = linea_upper.index("RAZONAMIENTO:")
            razonamiento = linea[idx + len("RAZONAMIENTO:"):].strip()
        elif "ACCION_P1:" in linea_upper:
            idx = linea_upper.index("ACCION_P1:")
            val = linea[idx + len("ACCION_P1:"):].strip().lower()
            if val:
                accion_p1 = val
        elif "ACCION_P2:" in linea_upper:
            idx = linea_upper.index("ACCION_P2:")
            val = linea[idx + len("ACCION_P2:"):].strip().lower()
            if val:
                accion_p2 = val
        elif "PREDICT:" in linea_upper:
            idx = linea_upper.index("PREDICT:")
            predict = linea[idx + len("PREDICT:"):].strip()
    return razonamiento, accion_p1, accion_p2, predict


def construir_orden_desde_texto(accion_str, battle, idx_pokemon):
    activos = [p for p in battle.active_pokemon if p is not None]
    rivales = [p for p in battle.opponent_active_pokemon if p is not None]

    if idx_pokemon >= len(activos) or not accion_str:
        return None

    # Detectar switch voluntario
    accion_lower = accion_str.strip().lower()
    if accion_lower.startswith("switch:"):
        nombre_switch = accion_lower.replace("switch:", "").strip().replace("-", "").replace(" ", "")
        switches = battle.available_switches
        if switches and isinstance(switches[0], list):
            switches = [p for slot in switches for p in slot if p is not None]
        if not switches:
            print(f"  [Switch {nombre_switch}: no hay switches disponibles — señal de corrección]")
            return f"SWITCH_INVALIDO:{nombre_switch}"
        for p in switches:
            p_nombre = p.species.lower().replace("-", "").replace(" ", "")
            if nombre_switch in p_nombre or p_nombre in nombre_switch:
                print(f"  [Switch voluntario: {p.species}]")
                return Player.create_order(p)
        nombres_disponibles = [p.species for p in switches]
        print(f"  [Switch {nombre_switch} no encontrado. Disponibles: {nombres_disponibles} — señal de corrección]")
        return f"SWITCH_INVALIDO:{nombre_switch}"

    # Detectar teracristalización: "tera" o "teracristalizar" en la acción
    teracristalizar = False
    if "tera" in accion_lower:
        # Verificar si la tera está disponible para este Pokémon
        tera_disponible = False
        if battle.available_moves and idx_pokemon < len(battle.available_moves):
            for m in battle.available_moves[idx_pokemon]:
                if hasattr(m, 'can_tera') and m.can_tera:
                    tera_disponible = True
                    break
        if tera_disponible:
            teracristalizar = True
        else:
            print(f"  [Tera no disponible para P{idx_pokemon+1}, ignorando tera]")
        # Limpiar la parte de tera del string para parsear el movimiento
        accion_lower = accion_lower.split("(")[0].strip()
        accion_lower = accion_lower.replace("teracristalizar", "").replace("tera", "").strip()

    movimientos = []
    if battle.available_moves and idx_pokemon < len(battle.available_moves):
        movimientos = battle.available_moves[idx_pokemon]

    if not movimientos:
        return None

    partes = accion_str.strip().split()
    if not partes:
        return None

    # Determinar target rival
    accion_lower = accion_str.lower()
    if "rival2" in accion_lower or " r2" in accion_lower or (partes and partes[-1].lower() == "r2"):
        target_slot = DoubleBattle.OPPONENT_2_POSITION
        if len(rivales) < 2:
            target_slot = DoubleBattle.OPPONENT_1_POSITION
    else:
        target_slot = DoubleBattle.OPPONENT_1_POSITION

    # Normalizar nombre del movimiento
    palabras_ignorar = {"rival1", "rival2", "r1", "r2"}
    nombre_busqueda = partes[0].replace("-", "").replace(" ", "").lower()
    nombre_completo = "".join(
        p for p in partes if p.lower() not in palabras_ignorar
    ).replace("-", "").replace(" ", "").lower()

    movimiento = None

    # Match exacto
    for m in movimientos:
        m_id = m.id.lower().replace("-", "").replace(" ", "")
        if m_id == nombre_busqueda or m_id == nombre_completo:
            movimiento = m
            break

    # Match parcial
    if movimiento is None:
        for m in movimientos:
            m_id = m.id.lower().replace("-", "").replace(" ", "")
            if nombre_busqueda in m_id or m_id in nombre_busqueda:
                movimiento = m
                break

    # Fallback al movimiento con más daño
    if movimiento is None:
        movimientos_danio = [m for m in movimientos if m.base_power > 0]
        movimiento = movimientos_danio[0] if movimientos_danio else movimientos[0]
        print(f"  [Fallback movimiento: {movimiento.id}]")

    # Usar el target del movimiento desde los datos de poke-env
    move_target = movimiento.target if hasattr(movimiento, 'target') else None
    move_target_name = move_target.name if hasattr(move_target, 'name') else ""

    # Movimientos que afectan solo al usuario o al campo (sin target externo)
    if move_target_name in ("SELF", "ALLY_SIDE", "FOE_SIDE", "ALL", "ALL_ADJACENT",
                            "ALL_ADJACENT_FOES", "ALLIES", "ALLY_TEAM"):
        return Player.create_order(movimiento, terastallize=teracristalizar)

    # Movimientos dirigidos al aliado
    if move_target_name in ("ADJACENT_ALLY", "ADJACENT_ALLY_OR_SELF"):
        target_aliado = (DoubleBattle.POKEMON_2_POSITION
                        if idx_pokemon == 0
                        else DoubleBattle.POKEMON_1_POSITION)
        return Player.create_order(movimiento, move_target=target_aliado,
                                   terastallize=teracristalizar)

    if not rivales:
        return Player.create_order(movimiento, terastallize=teracristalizar)

    if teracristalizar:
        print(f"  [Teracristalización activada con {movimiento.id}]")

    return Player.create_order(movimiento, move_target=target_slot,
                               terastallize=teracristalizar)


class GeminiVGCBot(Player):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cliente = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.historial = []
        # Rastrear en qué turno entró cada Pokémon propio en campo
        self._turno_entrada = {}  # species -> turno en que entró
        self._activos_turno_anterior = set()  # species activos el turno anterior
        self._ots_rival = {}  # battle_tag -> lista de TeambuilderPokemon del rival
        self._ev_defensa_rival = {}  # species -> {'def': mult_estimado, 'spd': mult_estimado}
        self._ultimo_dano_esperado = {}  # species -> {stat: (pct_min, pct_max)} del último turno
        # Registro estructurado del combate por battle_tag
        self._registro_rival = {}  # battle_tag -> {species: {movs, protects, objeto, tera}}
        self._ultimo_protect = {}  # battle_tag -> {species: turno en que usó Protect}
        # Velocidad mínima inferida por observación: {battle_tag -> {species -> vel_minima_observada}}
        self._vel_minima_rival = {}

    async def _handle_challenge_request(self, split_message):
        challenging_player = split_message[2].strip()
        if challenging_player != self.username:
            if len(split_message) >= 6:
                formato_recibido = split_message[5]
                formato_base = self._format.split("@@@")[0].strip()
                formato_recibido_base = formato_recibido.split("@@@")[0].strip()
                if formato_recibido == self._format or formato_recibido_base == formato_base:
                    await self._challenge_queue.put(challenging_player)

    async def _handle_battle_message(self, split_messages):
        # Interceptar showteam del rival en custom game y parsear directamente
        for split_message in split_messages:
            if len(split_message) > 3 and split_message[1] == "showteam":
                role = split_message[2]
                packed = "|".join(split_message[3:])
                if role != self._current_battle_role():
                    try:
                        from poke_env.teambuilder import Teambuilder
                        mons = Teambuilder.parse_packed_team(packed)
                        battle_tag = split_messages[0][0].lstrip(">")
                        self._ots_rival[battle_tag] = mons
                        battle_tag_base = battle_tag.split("@@@")[0].strip()
                        if battle_tag_base != battle_tag:
                            self._ots_rival[battle_tag_base] = mons
                    except Exception as e:
                        print(f"[OTS ERROR]: {e}")
            # Detectar fin de combate
            elif len(split_message) > 1 and split_message[1] == "win":
                # Análisis automático de errores desactivado por ahora
                # El análisis de Gemini con solo el historial de texto no es suficientemente preciso
                self.historial = []
                tag = split_messages[0][0].lstrip(">")
                for d in [self._registro_rival, self._ultimo_protect, self._ots_rival]:
                    if tag in d:
                        del d[tag]
        await super()._handle_battle_message(split_messages)

    def _current_battle_role(self):
        # Obtener el rol del bot en el combate actual
        for battle in self._battles.values():
            if hasattr(battle, 'player_role') and battle.player_role:
                return battle.player_role
        return "p2"  # default

    async def _create_battle(self, split_message):
        # En custom game el battle_tag usa solo el formato base sin @@@
        formato_base = self._format.split("@@@")[0].strip()
        if split_message[1] == formato_base and len(split_message) >= 2:
            formato_original = self._format
            self._format = formato_base
            try:
                battle = await super()._create_battle(split_message)
            finally:
                self._format = formato_original
            return battle
        return await super()._create_battle(split_message)

    async def _handle_battle_request(self, battle, maybe_default_order=False):
        if battle.teampreview and "customgame" in battle.battle_tag.lower():
            mensaje = self.teampreview(battle)
            if mensaje:
                await self.ps_client.send_message(mensaje, battle.battle_tag)
                return
        await super()._handle_battle_request(battle, maybe_default_order)


    def _actualizar_registro_rival(self, battle):
        """Lee las observaciones del ultimo turno y actualiza el registro del rival."""
        tag = battle.battle_tag
        if tag not in self._registro_rival:
            self._registro_rival[tag] = {}
        if tag not in self._ultimo_protect:
            self._ultimo_protect[tag] = {}
        if tag not in self._vel_minima_rival:
            self._vel_minima_rival[tag] = {}
        registro = self._registro_rival[tag]
        protect_propio = self._ultimo_protect[tag]
        vel_minima = self._vel_minima_rival[tag]
        if not hasattr(battle, "observations") or not battle.observations:
            return
        ultimo_turno = max(battle.observations.keys())
        obs = battle.observations.get(ultimo_turno)
        if not obs or not obs.events:
            return
        for evento in obs.events:
            if len(evento) < 3:
                continue
            tipo = evento[1]
            rol_rival = "p1" if self._current_battle_role() == "p2" else "p2"
            rol_propio = "p2" if self._current_battle_role() == "p2" else "p1"
            if tipo == "move":
                usuario = evento[2] if len(evento) > 2 else ""
                movimiento = evento[3] if len(evento) > 3 else ""
                if usuario.startswith(rol_rival):
                    species = usuario.split(": ")[-1].strip()
                    if species not in registro:
                        registro[species] = {"movs": {}, "protects": 0, "tera": False}
                    movs = registro[species]["movs"]
                    movs[movimiento] = movs.get(movimiento, 0) + 1
                    if movimiento.lower() in ("protect", "detect", "spikyshield", "kingsshield",
                                              "silktrap", "banefulbunker", "wideguard", "quickguard"):
                        registro[species]["protects"] += 1
                # Rastrear Protect propio para saber si puede usarlo el siguiente turno
                elif usuario.startswith(rol_propio):
                    species = usuario.split(": ")[-1].strip()
                    if movimiento.lower() in ("protect", "detect", "spikyshield", "kingsshield",
                                              "silktrap", "banefulbunker", "wideguard", "quickguard"):
                        protect_propio[species] = ultimo_turno
            elif tipo == "-terastallize":
                usuario = evento[2] if len(evento) > 2 else ""
                if usuario.startswith(rol_rival):
                    species = usuario.split(": ")[-1].strip()
                    if species not in registro:
                        registro[species] = {"movs": {}, "protects": 0, "tera": False}
                    registro[species]["tera"] = True
            elif tipo in ("-item", "-enditem"):
                usuario = evento[2] if len(evento) > 2 else ""
                objeto = evento[3] if len(evento) > 3 else ""
                if usuario.startswith(rol_rival):
                    species = usuario.split(": ")[-1].strip()
                    if species not in registro:
                        registro[species] = {"movs": {}, "protects": 0, "tera": False}
                    registro[species]["objeto_revelado"] = objeto

        # Inferir velocidad mínima del rival comparando orden de actuación en el log
        # Si un rival usó un movimiento antes que uno de mis Pokémon que debería ser más rápido,
        # el rival tiene al menos tanta velocidad como mi Pokémon
        try:
            if not battle.observations:
                return
            ultimo_turno = max(battle.observations.keys())
            obs = battle.observations.get(ultimo_turno)
            if not obs or not obs.events:
                return

            rol_rival = "p1" if self._current_battle_role() == "p2" else "p2"
            rol_propio = "p2" if self._current_battle_role() == "p2" else "p1"

            # Extraer orden de movimientos del turno
            orden_movimientos = []
            for evento in obs.events:
                if len(evento) >= 4 and evento[1] == "move":
                    usuario = evento[2]
                    es_rival = usuario.startswith(rol_rival)
                    species = usuario.split(": ")[-1].strip()
                    orden_movimientos.append((species, es_rival))

            # Buscar casos donde rival actuó antes que mis Pokémon activos
            activos_propios_ahora = [p for p in battle.active_pokemon if p is not None]
            activos_rivales_ahora = [p for p in battle.opponent_active_pokemon if p is not None]

            for idx_rival, (species_rival, es_rival) in enumerate(orden_movimientos):
                if not es_rival:
                    continue
                # Ver si actuó antes que algún Pokémon propio
                for idx_propio, (species_propio, es_propio_mov) in enumerate(orden_movimientos):
                    if es_propio_mov or idx_propio <= idx_rival:
                        continue
                    # El rival actuó ANTES que mi Pokémon — inferir velocidad
                    p_propio = next((p for p in activos_propios_ahora
                                    if p.species.lower() == species_propio.lower()), None)
                    if not p_propio:
                        continue
                    vel_propia = None
                    if hasattr(p_propio, 'stats') and p_propio.stats:
                        vel_propia = p_propio.stats.get('spe')
                    if vel_propia is None:
                        continue
                    # Aplicar boost propio
                    spe_boost_propio = p_propio.boosts.get('spe', 0) if hasattr(p_propio, 'boosts') else 0
                    if spe_boost_propio > 0:
                        vel_propia = math.floor(vel_propia * (2 + spe_boost_propio) / 2)
                    elif spe_boost_propio < 0:
                        vel_propia = math.floor(vel_propia * 2 / (2 - spe_boost_propio))
                    # El rival es al menos tan rápido como mi Pokémon en ese momento
                    vel_actual = vel_minima.get(species_rival, 0)
                    if vel_propia > vel_actual:
                        vel_minima[species_rival] = vel_propia
                        print(f"  [Vel inferida] {species_rival} tiene al menos {vel_propia} de velocidad")
        except Exception:
            pass

    async def _battle_finished_callback(self, battle):
        """Llamado al final de cada combate para analizar errores."""
        try:
            resultado = "GANADO" if battle.won else "PERDIDO"
            print(f"\n[Combate {resultado}] Analizando errores...")

            # Construir resumen del combate para análisis
            historial_str = chr(10).join(self.historial[-20:]) if self.historial else "Sin historial"

            prompt_analisis = f"""Analiza este combate de Pokémon VGC que el bot {resultado}.

HISTORIAL DE DECISIONES DEL BOT:
{historial_str}

Identifica entre 1 y 5 errores que cometió el bot. Cada error en UNA LÍNEA CORTA (máximo 120 caracteres), comenzando con el tipo entre corchetes.

Formato estricto — cada línea máximo 120 caracteres:
[MOVIMIENTO] No uses Protect si el Pokémon no tiene Protect en su moveset
[SWITCH] No hagas switch a Pokémon que no están en MI BANCO
[COMMANDER] Tatsugiri puede actuar cuando Dondozo cae

Responde SOLO con los errores, uno por línea, sin texto adicional."""

            loop = asyncio.get_event_loop()
            respuesta = await loop.run_in_executor(
                None,
                lambda: self.cliente.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt_analisis,
                    config=types.GenerateContentConfig(
                        max_output_tokens=500,
                        temperature=0.1,
                    )
                )
            )
            texto = respuesta.text.strip()
            errores = [l.strip()[:150] for l in texto.split("\n") if l.strip() and l.strip().startswith("[")]
            if errores:
                guardar_errores(errores)
                print(f"[Aprendizaje] {len(errores)} errores guardados:")
                for e in errores:
                    print(f"  {e}")
            else:
                print("[Aprendizaje] No se detectaron errores claros")
        except Exception as e:
            print(f"[Error en análisis de combate: {e}]")
        finally:
            # Limpiar estado del combate
            self.historial = []
            tag = battle.battle_tag
            if tag in self._registro_rival:
                del self._registro_rival[tag]
            if tag in self._ultimo_protect:
                del self._ultimo_protect[tag]
            if tag in self._ots_rival:
                del self._ots_rival[tag]

    def _fallback_inteligente(self, battle):
        """Fallback que elige el mejor movimiento disponible en lugar de uno aleatorio."""
        activos = [p for p in battle.active_pokemon if p is not None]
        rivales = [p for p in battle.opponent_active_pokemon if p is not None]
        protect_moves = {"protect", "detect", "spikyshield", "kingsshield",
                         "silktrap", "banefulbunker", "wideguard", "quickguard"}

        ordenes = []
        for i, p in enumerate(activos):
            movs = battle.available_moves[i] if battle.available_moves and i < len(battle.available_moves) else []
            switches = battle.available_switches or []
            if switches and isinstance(switches[0], list):
                switches = [sw for slot in switches for sw in slot if sw is not None]

            # Si no hay movimientos, hacer switch si es posible
            if not movs and switches:
                ordenes.append(Player.create_order(switches[0]))
                continue
            if not movs:
                continue

            # Excluir Protect si se usó el turno anterior
            tag = battle.battle_tag
            ultimo_protect = self._ultimo_protect.get(tag, {})
            turno_protect = ultimo_protect.get(p.species)
            protect_bloqueado = (turno_protect is not None and turno_protect == battle.turn - 1)

            movs_disponibles = [m for m in movs
                                if not (protect_bloqueado and m.id.lower() in protect_moves)]
            if not movs_disponibles:
                movs_disponibles = movs  # si no queda nada, usar todos

            # Elegir el movimiento con mayor daño esperado contra el rival más débil
            mejor_mov = None
            mejor_score = -1
            for m in movs_disponibles:
                if m.base_power <= 0:
                    continue
                bp_efectivo = m.base_power
                mov_id = m.id.lower()
                if mov_id == "surgingstrikes":
                    bp_efectivo = 112
                elif mov_id in ("dualwingbeat", "doublekick"):
                    bp_efectivo = m.base_power * 2
                elif mov_id in ("bulletseed", "rockblast", "watershuriken"):
                    bp_efectivo = m.base_power * 3
                score = bp_efectivo
                if rivales:
                    target = rivales[0]
                    try:
                        mult = m.type.damage_multiplier(target.type_1, target.type_2, type_chart=TYPE_CHART)
                        score = bp_efectivo * mult
                    except Exception:
                        pass
                if score > mejor_score:
                    mejor_score = score
                    mejor_mov = m

            # Si no hay movimiento de daño, usar el primero disponible que no sea Protect bloqueado
            if not mejor_mov:
                for m in movs_disponibles:
                    if not protect_bloqueado or m.id.lower() not in protect_moves:
                        mejor_mov = m
                        break
                if not mejor_mov:
                    mejor_mov = movs[0]

            if mejor_mov:
                target_slot = DoubleBattle.OPPONENT_1_POSITION
                if rivales and hasattr(mejor_mov, 'target') and mejor_mov.target:
                    target_name = mejor_mov.target.name if hasattr(mejor_mov.target, 'name') else ''
                    if target_name not in ('SELF', 'ALLY_SIDE', 'FOE_SIDE', 'ALL', 'ALL_ADJACENT',
                                           'ALL_ADJACENT_FOES', 'ALLIES', 'ALLY_TEAM'):
                        target_slot = DoubleBattle.OPPONENT_1_POSITION
                ordenes.append(Player.create_order(mejor_mov, move_target=target_slot))

        if not ordenes:
            return self.choose_random_doubles_move(battle)
        if len(ordenes) == 1:
            return ordenes[0]
        try:
            return DoubleBattleOrder(ordenes[0], ordenes[1])
        except Exception:
            return ordenes[0]

    async def _corregir_switch_invalido(self, battle, idx_pokemon, nombre_invalido, razonamiento_previo):
        """Segunda llamada a Gemini cuando detecta un switch inválido."""
        activos = [p for p in battle.active_pokemon if p is not None]
        switches = battle.available_switches or []
        if switches and isinstance(switches[0], list):
            switches = [p for slot in switches for p in slot if p is not None]
        movs = battle.available_moves[idx_pokemon] if battle.available_moves and idx_pokemon < len(battle.available_moves) else []

        banco_str = ""
        if switches:
            banco_str = ", ".join(f"switch:{p.species.lower().replace('-','').replace(' ','')} ({p.species} HP:{p.current_hp_fraction*100:.0f}%)" for p in switches)
        else:
            banco_str = "ninguno disponible"

        movs_str = ""
        if movs:
            movs_str = ", ".join(m.id for m in movs)

        pokemon_activo = activos[idx_pokemon].species if idx_pokemon < len(activos) else "desconocido"

        prompt_correccion = f"""Tu acción anterior fue switch:{nombre_invalido} pero ese Pokémon NO está en tu equipo seleccionado para este combate.

Pokémon activo: {pokemon_activo}
Movimientos disponibles: {movs_str}
Switches disponibles: {banco_str}

Tu razonamiento previo fue: {razonamiento_previo}

Dado ese contexto, elige UNA acción válida de las opciones de arriba.
Responde SOLO con:
ACCION: [nombre_movimiento] [rival1|rival2] O switch:[nombre_exacto]
RAZONAMIENTO: [una frase explicando por qué]"""

        try:
            texto = await self._llamar_gemini(prompt_correccion)
            # Parsear respuesta simple
            accion = None
            for linea in texto.strip().split('\n'):
                linea = linea.strip().replace('**','')
                if 'ACCION:' in linea.upper():
                    idx = linea.upper().index('ACCION:')
                    accion = linea[idx + len('ACCION:'):].strip().lower()
                    break
            if accion:
                print(f"  [Corrección switch: {accion}]")
                resultado = construir_orden_desde_texto(accion, battle, idx_pokemon)
                if resultado and not isinstance(resultado, str):
                    return resultado
        except Exception as e:
            print(f"  [Error corrección switch: {e}]")

        # Si la corrección también falla, usar fallback inteligente
        return None

    async def _llamar_gemini(self, prompt):
        loop = asyncio.get_event_loop()
        # Errores aprendidos automáticos desactivados — análisis no suficientemente preciso
        respuesta = await loop.run_in_executor(
            None,
            lambda: self.cliente.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    max_output_tokens=4096,
                    temperature=0.2,
                )
            )
        )
        return respuesta.text

    def teampreview(self, battle):
        equipo_propio = list(battle.team.values())[:6]

        # En doubles custom game seleccionamos los 2 mejores para abrir con Gemini
        if "customgame" in battle.battle_tag.lower():
            # Buscar OTS por varias claves posibles
            ots = (self._ots_rival.get(battle.battle_tag) or
                   self._ots_rival.get(battle.battle_tag.split("@@@")[0].strip()) or
                   next((v for k, v in self._ots_rival.items()
                         if battle.battle_tag.split("-")[0:4] == k.split("-")[0:4]), []))
            print(f"[TEAMPREVIEW DEBUG] battle_tag={battle.battle_tag} ots_len={len(ots)} ots_keys={list(self._ots_rival.keys())}")
            prompt = construir_prompt_teampreview(battle, es_custom=True, ots_rival=ots)
            try:
                respuesta = self.cliente.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        max_output_tokens=2048,
                        temperature=0.2,
                    )
                )
                texto = respuesta.text
                _, apertura, razonamiento = parsear_respuesta_teampreview(texto, len(equipo_propio))
                print(f"\n[TEAMPREVIEW] {razonamiento}")
                print(f"Apertura: {apertura}")
                if len(apertura) >= 2:
                    return "/team " + "".join(str(i) for i in apertura[:2])
                return "/team 12"
            except Exception as e:
                print(f"Error en teampreview custom: {e}")
                return "/team 12"
        prompt = construir_prompt_teampreview(battle)

        try:
            respuesta = self.cliente.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    max_output_tokens=4096,
                    temperature=0.2,
                )
            )
            texto = respuesta.text
            seleccion, apertura, razonamiento = parsear_respuesta_teampreview(
                texto, len(equipo_propio)
            )
            print(f"\n[TEAMPREVIEW] {razonamiento}")
            print(f"Selección: {seleccion}, Apertura: {apertura}")

        except Exception as e:
            print(f"Error en teampreview: {e}")
            seleccion = list(range(1, min(5, len(equipo_propio) + 1)))
            apertura = seleccion[:2]

        orden_final = list(apertura)
        for s in seleccion:
            if s not in orden_final:
                orden_final.append(s)
        orden_final = orden_final[:4]

        # Asegurarse de que hay exactamente 4 Pokémon válidos
        todos = list(range(1, len(equipo_propio) + 1))
        while len(orden_final) < 4:
            for x in todos:
                if x not in orden_final:
                    orden_final.append(x)
                    break

        for idx in orden_final:
            if 1 <= idx <= len(equipo_propio):
                equipo_propio[idx-1]._selected_in_teampreview = True

        team_str = "/team " + "".join(str(i) for i in orden_final)
        print(f"  [Enviando teampreview VGC: {team_str}]")
        return team_str

    async def choose_move(self, battle):
        activos = [p for p in battle.active_pokemon if p is not None]
        rivales = [p for p in battle.opponent_active_pokemon if p is not None]

        # Actualizar registro estructurado del rival
        self._actualizar_registro_rival(battle)

        if not rivales:
            return self.choose_random_doubles_move(battle)

        # Si solo hay switches disponibles (Pokémon cayó), dejar que poke-env lo maneje
        moves_disponibles = []
        if battle.available_moves:
            for slot in battle.available_moves:
                if slot:
                    moves_disponibles.extend(slot)

        if not moves_disponibles:
            return self.choose_random_doubles_move(battle)

        ots_rival = self._ots_rival.get(battle.battle_tag, [])
        registro_rival = self._registro_rival.get(battle.battle_tag, {})
        ultimo_protect = self._ultimo_protect.get(battle.battle_tag, {})
        vel_minima_rival = self._vel_minima_rival.get(battle.battle_tag, {})
        prompt = construir_prompt_turno(battle, self.historial, self._turno_entrada, ots_rival, registro_rival, ultimo_protect, vel_minima_rival)

        # Actualizar turno de entrada para Pokémon activos
        activos_ahora = {p.species for p in battle.active_pokemon if p is not None}
        for p in battle.active_pokemon:
            if p is not None:
                # Es primer turno si: nunca lo hemos visto O no estaba activo el turno anterior
                if p.species not in self._turno_entrada or p.species not in self._activos_turno_anterior:
                    self._turno_entrada[p.species] = battle.turn
        self._activos_turno_anterior = activos_ahora

        try:
            texto = await self._llamar_gemini(prompt)
            razonamiento, accion_p1_str, accion_p2_str, predict = parsear_respuesta_turno(texto)

            self.historial.append(
                f"T{battle.turn}: {razonamiento} | P1 usó: {accion_p1_str} | P2 usó: {accion_p2_str}"
            )

            def daño_accion_str(accion_str, idx_pokemon, activos_p, activos_r):
                """Calcula el daño estimado de una acción para mostrar en consola"""
                if not accion_str or accion_str.startswith("switch:") or not activos_r:
                    return ""
                try:
                    accion_lower = accion_str.lower().replace("tera","").strip()
                    partes = accion_lower.split()
                    if not partes:
                        return ""
                    nombre_mov = partes[0].replace("-","").replace(" ","")
                    movs_disp = battle.available_moves[idx_pokemon] if battle.available_moves and idx_pokemon < len(battle.available_moves) else []
                    movimiento = None
                    for m in movs_disp:
                        if m.id.lower().replace("-","") == nombre_mov:
                            movimiento = m
                            break
                    if not movimiento or movimiento.base_power <= 0:
                        return ""
                    atacante = activos_p[idx_pokemon] if idx_pokemon < len(activos_p) else None
                    if not atacante:
                        return ""
                    target_idx = 1 if "rival2" in accion_lower else 0
                    if target_idx >= len(activos_r):
                        target_idx = 0
                    defensor = activos_r[target_idx]
                    result = calcular_daño_aproximado(atacante, movimiento, defensor, battle)
                    if result:
                        pct_min, pct_max, mult = result
                        hp_actual = round(defensor.current_hp_fraction * 100)
                        ko = " ⚠️KO!" if pct_min >= hp_actual else (" ⚠️KO posible" if pct_max >= hp_actual else "")
                        return f" [{pct_min}-{pct_max}% daño | R{target_idx+1} HP:{hp_actual}%{ko}]"
                except Exception:
                    pass
                return ""

            dmg1 = daño_accion_str(accion_p1_str, 0, activos, rivales)
            dmg2 = daño_accion_str(accion_p2_str, 1, activos, rivales)

            print(f"\n{'='*60}")
            print(f"TURNO {battle.turn}")
            print(f"PREDICT: {predict}")
            print(f"RAZONAMIENTO: {razonamiento}")
            print(f"ACCION_P1: {accion_p1_str}{dmg1}")
            print(f"ACCION_P2: {accion_p2_str}{dmg2}")
            print(f"{'='*60}")

            try:
                orden1 = construir_orden_desde_texto(accion_p1_str, battle, 0) if accion_p1_str else None
            except Exception as e:
                print(f"  Error orden P1: {e}")
                orden1 = None

            # Detectar switch inválido en P1 y corregir con segunda llamada
            if isinstance(orden1, str) and orden1.startswith("SWITCH_INVALIDO:"):
                nombre_inv = orden1.split(":")[1]
                orden1 = await self._corregir_switch_invalido(battle, 0, nombre_inv, razonamiento)
                if orden1 is None:
                    orden1 = self._fallback_inteligente(battle)
                    return orden1

            try:
                orden2 = construir_orden_desde_texto(accion_p2_str, battle, 1) if accion_p2_str and len(activos) > 1 else None
            except Exception as e:
                print(f"  Error orden P2: {e}")
                orden2 = None

            # Detectar switch inválido en P2 y corregir con segunda llamada
            if isinstance(orden2, str) and orden2.startswith("SWITCH_INVALIDO:"):
                nombre_inv = orden2.split(":")[1]
                orden2 = await self._corregir_switch_invalido(battle, 1, nombre_inv, razonamiento)

            if orden1 is None:
                print("  Fallback P1 inteligente")
                return self._fallback_inteligente(battle)

            if len(activos) == 1:
                return orden1

            if len(activos) > 1 and orden2 is None:
                # Intentar construir orden2 con el mejor movimiento disponible de P2
                # que no sea inefectivo contra los rivales
                try:
                    movs_p2 = battle.available_moves[1] if battle.available_moves and len(battle.available_moves) > 1 else []
                    rivales_activos = [p for p in battle.opponent_active_pokemon if p is not None]
                    if movs_p2 and rivales_activos:
                        # Filtrar movimientos que tengan al menos algún efecto
                        from poke_env.battle.move import Move
                        movs_validos = []
                        for m in movs_p2:
                            if m.base_power > 0:
                                # Comprobar si afecta a algún rival
                                for rival in rivales_activos:
                                    mult = m.type.damage_multiplier(
                                        rival.type_1, rival.type_2,
                                        type_chart=TYPE_CHART
                                    )
                                    if mult > 0:
                                        movs_validos.append(m)
                                        break
                        if not movs_validos:
                            movs_validos = movs_p2
                        mejor_mov = max(movs_validos, key=lambda m: m.base_power)
                        orden2 = construir_orden_desde_texto(mejor_mov.id, battle, 1)
                        print(f"  [P2 fallback: {mejor_mov.id}]")
                except Exception as e:
                    print(f"  [P2 fallback error: {e}]")

            if orden1 is None or (len(activos) > 1 and orden2 is None):
                print("  Fallback total inteligente")
                return self._fallback_inteligente(battle)

            if isinstance(orden1, DoubleBattleOrder):
                return orden1
            if orden2 and isinstance(orden2, DoubleBattleOrder):
                return orden2

            if len(activos) == 1 or orden2 is None:
                return orden1

            resultado = DoubleBattleOrder(orden1, orden2)
            print(f"  [Orden enviada: {resultado.message}]")
            return resultado

        except Exception as e:
            print(f"\n[ERROR T{battle.turn}]: {e}")
            return self.choose_random_doubles_move(battle)


async def main():
    import websockets
    import json as json_lib

    arg = sys.argv[1].lower() if len(sys.argv) > 1 else "regg"
    regulacion = FORMATO_POR_ARG.get(arg, "gen9vgc2024regg")
    equipo = random.choice(EQUIPOS_POR_REGULACION[regulacion])

    bot = GeminiVGCBot(
        account_configuration=AccountConfiguration(
            "StockfishVGC",
            os.getenv("SHOWDOWN_PASSWORD", "Carlos12102003._")
        ),
        server_configuration=ShowdownServerConfiguration,
        battle_format=regulacion,
        team=equipo,
        accept_open_team_sheet=True,
        start_listening=True
    )

    print(f"StockfishVGC (Gemini) conectado en formato: {regulacion}")
    print(f"Equipo cargado aleatoriamente de {len(EQUIPOS_POR_REGULACION[regulacion])} disponibles")

    backend_url = os.getenv("BACKEND_WS_URL", "ws://localhost:3000/ws")
    bot_key = os.getenv("JWT_SECRET", "porybot_super_secret_key_changeme_in_production")
    ws_url = f"{backend_url}?bot_key={bot_key}"

    async def escuchar_backend():
        while True:
            try:
                print(f"Conectando al backend PoryBot...")
                async with websockets.connect(ws_url) as ws:
                    print("Bot conectado al backend PoryBot ✅")
                    async for mensaje in ws:
                        try:
                            data = json_lib.loads(mensaje)
                            if data.get("type") == "start_battle":
                                nick = data.get("nick")
                                reg = data.get("regulation", arg)
                                formato = FORMATO_POR_ARG.get(reg, regulacion)
                                print(f"[PoryBot] Desafiando a {nick} en formato {formato}")
                                bot._format = formato
                                await bot.send_challenges(nick, 1)
                        except Exception as e:
                            print(f"[Error procesando mensaje backend]: {e}")
            except Exception as e:
                print(f"[Backend WS desconectado]: {e}. Reconectando en 5s...")
                await asyncio.sleep(5)

    await asyncio.gather(
        bot.accept_challenges(None, 100),
        escuchar_backend()
    )


if __name__ == "__main__":
    asyncio.run(main())