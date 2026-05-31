"""
PoryBot — Launcher con combates simultáneos
Crea un bot independiente por cada combate.
"""
import asyncio
import os
import json
import websockets
from dotenv import load_dotenv
from poke_env import AccountConfiguration, ShowdownServerConfiguration
from poke_env.teambuilder.constant_teambuilder import ConstantTeambuilder

from gemini_bot_base import GeminiVGCBot

from gemini_bot_regf import SYSTEM_PROMPT as SYSTEM_PROMPT_REGF
from gemini_bot_regg import SYSTEM_PROMPT as SYSTEM_PROMPT_REGG
from gemini_bot_regi import SYSTEM_PROMPT as SYSTEM_PROMPT_REGI
from gemini_bot_regma import SYSTEM_PROMPT as SYSTEM_PROMPT_REGMA

load_dotenv()

FORMATO_POR_ARG = {
    "regg":  "gen9vgc2024regg",
    "regf":  "gen9vgc2026regf",
    "regi":  "gen9vgc2026regi",
    "regma": "gen9championsvgc2026regma",
}

SYSTEM_PROMPT_POR_FORMATO = {
    "gen9vgc2024regg":           SYSTEM_PROMPT_REGG,
    "gen9vgc2026regf":           SYSTEM_PROMPT_REGF,
    "gen9vgc2026regi":           SYSTEM_PROMPT_REGI,
    "gen9championsvgc2026regma": SYSTEM_PROMPT_REGMA,
}

FORMATO_DEFAULT = "gen9vgc2026regf"

BOT_USERNAME = os.getenv("SHOWDOWN_USERNAME", "StockfishVGC")
BOT_PASSWORD = os.getenv("SHOWDOWN_PASSWORD", "")

# Registro de combates activos para logs
combates_activos = {}


def crear_bot(formato: str, team=None) -> GeminiVGCBot:
    system_prompt = SYSTEM_PROMPT_POR_FORMATO.get(formato, SYSTEM_PROMPT_REGF)

    if "regma" in formato:
        try:
            from champions_pokedex import parchear_pokedex_champions
            parchear_pokedex_champions()
        except Exception as e:
            print(f"[Launcher] No se pudo parchear el Pokédex de Champions: {e}")

    bot = GeminiVGCBot(
        system_prompt=system_prompt,
        account_configuration=AccountConfiguration(BOT_USERNAME, BOT_PASSWORD),
        server_configuration=ShowdownServerConfiguration,
        battle_format=formato,
        team=team,
        accept_open_team_sheet=True,
        start_listening=True,
    )
    return bot


async def lanzar_combate(nick: str, formato: str, paste: str | None, battle_id: str):
    """Crea un bot dedicado para este combate y lo ejecuta de forma independiente."""
    combate_id = f"{nick}@{formato}"
    print(f"[Launcher] ▶ Iniciando combate para {nick} en {formato} (ID: {battle_id[:8]}...)")

    try:
        # Teambuilder con el equipo de la BD si viene el paste
        team = ConstantTeambuilder(paste) if paste else None

        # Crear bot dedicado para este combate
        bot = crear_bot(formato, team=team)
        combates_activos[battle_id] = bot

        # Enviar challenge y esperar a que se complete el combate
        await asyncio.gather(
            bot.send_challenges(nick, 1),
            bot.accept_challenges(nick, 1),
        )

        print(f"[Launcher] ✓ Combate {combate_id} finalizado")

    except Exception as e:
        print(f"[Launcher] ✗ Error en combate {combate_id}: {e}")
    finally:
        combates_activos.pop(battle_id, None)


async def main():
    backend_url = os.getenv("BACKEND_WS_URL", "ws://localhost:3000/ws")
    bot_key = os.getenv("JWT_SECRET", "porybot_super_secret_key_changeme_in_production")
    ws_url = f"{backend_url}?bot_key={bot_key}"

    print(f"[Launcher] StockfishVGC iniciado — combates simultáneos activados")
    print(f"[Launcher] Regulaciones disponibles: {', '.join(FORMATO_POR_ARG.keys())}")

    async def escuchar_backend():
        while True:
            try:
                print("[Launcher] Conectando al backend PoryBot...")
                async with websockets.connect(
                    ws_url, ping_interval=20, ping_timeout=60, close_timeout=10
                ) as ws:
                    print("[Launcher] Bot conectado al backend PoryBot ✅")

                    async for mensaje in ws:
                        try:
                            data = json.loads(mensaje)

                            if data.get("type") == "start_battle":
                                nick      = data.get("nick")
                                reg       = data.get("regulation", "regf")
                                paste     = data.get("paste")
                                battle_id = data.get("battleId", "unknown")

                                formato = FORMATO_POR_ARG.get(reg, FORMATO_DEFAULT)

                                n_activos = len(combates_activos)
                                print(f"[Launcher] Nueva solicitud: {nick} en {formato} "
                                      f"(combates activos: {n_activos})")

                                # Lanzar combate como tarea independiente — no bloqueante
                                asyncio.create_task(
                                    lanzar_combate(nick, formato, paste, battle_id)
                                )

                        except Exception as e:
                            print(f"[Launcher] Error procesando mensaje: {e}")

            except Exception as e:
                print(f"[Launcher] Backend WS desconectado: {e}. Reconectando en 5s...")
                await asyncio.sleep(5)

    await escuchar_backend()


if __name__ == "__main__":
    asyncio.run(main())