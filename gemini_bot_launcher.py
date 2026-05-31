"""
PoryBot — Launcher unificado del bot VGC
Arranca una sola vez y gestiona todas las regulaciones.
El equipo y la regulación vienen del backend via WebSocket.

Uso:
    python gemini_bot_launcher.py
"""
import asyncio
import os
import json
import websockets
from dotenv import load_dotenv
from poke_env import AccountConfiguration, ShowdownServerConfiguration
from poke_env.teambuilder.constant_teambuilder import ConstantTeambuilder

from gemini_bot_base import GeminiVGCBot

# Importar SYSTEM_PROMPTs de cada regulación
from gemini_bot_regf import SYSTEM_PROMPT as SYSTEM_PROMPT_REGF
from gemini_bot_regg import SYSTEM_PROMPT as SYSTEM_PROMPT_REGG
from gemini_bot_regi import SYSTEM_PROMPT as SYSTEM_PROMPT_REGI
from gemini_bot_regma import SYSTEM_PROMPT as SYSTEM_PROMPT_REGMA

load_dotenv()

# Mapeado de regulación (valor que llega del backend) → formato Showdown
FORMATO_POR_ARG = {
    "regg":  "gen9vgc2024regg",
    "regf":  "gen9vgc2026regf",
    "regi":  "gen9vgc2026regi",
    "regma": "gen9championsvgc2026regma",
}

# Mapeado de formato Showdown → SYSTEM_PROMPT
SYSTEM_PROMPT_POR_FORMATO = {
    "gen9vgc2024regg":           SYSTEM_PROMPT_REGG,
    "gen9vgc2026regf":           SYSTEM_PROMPT_REGF,
    "gen9vgc2026regi":           SYSTEM_PROMPT_REGI,
    "gen9championsvgc2026regma": SYSTEM_PROMPT_REGMA,
}

# Formato por defecto al arrancar
FORMATO_DEFAULT = "gen9vgc2026regf"

BOT_USERNAME = "StockfishVGC"
BOT_PASSWORD = "Carlos12102003._"


def crear_bot(formato: str) -> GeminiVGCBot:
    """Crea una instancia del bot con el SYSTEM_PROMPT correcto para el formato dado."""
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
        team=None,
        accept_open_team_sheet=True,
        start_listening=True,
    )
    return bot


async def main():
    backend_url = os.getenv("BACKEND_WS_URL", "ws://localhost:3000/ws")
    bot_key = os.getenv("JWT_SECRET", "porybot_super_secret_key_changeme_in_production")
    ws_url = f"{backend_url}?bot_key={bot_key}"

    # Crear bot inicial con el formato por defecto
    bot = crear_bot(FORMATO_DEFAULT)
    formato_actual = FORMATO_DEFAULT

    print(f"[Launcher] StockfishVGC iniciado — formato por defecto: {FORMATO_DEFAULT}")
    print(f"[Launcher] Regulaciones disponibles: {', '.join(FORMATO_POR_ARG.keys())}")

    async def escuchar_backend():
        nonlocal bot, formato_actual

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
                                nick       = data.get("nick")
                                reg        = data.get("regulation", "regf")
                                paste      = data.get("paste")
                                battle_id  = data.get("battleId")

                                formato = FORMATO_POR_ARG.get(reg, FORMATO_DEFAULT)

                                # Si el formato cambió, recrear el bot con el nuevo SYSTEM_PROMPT
                                if formato != formato_actual:
                                    print(f"[Launcher] Cambiando regulación: {formato_actual} → {formato}")
                                    bot._format = formato
                                    bot._system_prompt = SYSTEM_PROMPT_POR_FORMATO.get(formato, SYSTEM_PROMPT_REGF)
                                    formato_actual = formato
                                else:
                                    bot._format = formato

                                # Usar el equipo de la BD si viene el paste
                                if paste:
                                    bot._team = ConstantTeambuilder(paste)
                                    print(f"[Launcher] Equipo de la BD cargado para {nick}")
                                else:
                                    bot._team = None
                                    print(f"[Launcher] Sin equipo en BD — el bot usará su equipo por defecto")

                                print(f"[Launcher] Desafiando a {nick} en formato {formato}")
                                await bot.send_challenges(nick, 1)

                        except Exception as e:
                            print(f"[Launcher] Error procesando mensaje: {e}")

            except Exception as e:
                print(f"[Launcher] Backend WS desconectado: {e}. Reconectando en 5s...")
                await asyncio.sleep(5)

    await asyncio.gather(
        bot.accept_challenges(None, 100),
        escuchar_backend()
    )


if __name__ == "__main__":
    asyncio.run(main())