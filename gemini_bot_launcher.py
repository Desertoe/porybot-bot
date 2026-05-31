"""
PoryBot — Launcher unificado del bot VGC con watchdog
"""
import asyncio
import os
import json
import time
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

ultimo_combate = {"tiempo": time.time(), "en_combate": False}


def crear_bot(formato: str) -> GeminiVGCBot:
    system_prompt = SYSTEM_PROMPT_POR_FORMATO.get(formato, SYSTEM_PROMPT_REGF)
    if "regma" in formato:
        try:
            from champions_pokedex import parchear_pokedex_champions
            parchear_pokedex_champions()
        except Exception as e:
            print(f"[Launcher] No se pudo parchear el Pokédex de Champions: {e}")
    return GeminiVGCBot(
        system_prompt=system_prompt,
        account_configuration=AccountConfiguration(BOT_USERNAME, BOT_PASSWORD),
        server_configuration=ShowdownServerConfiguration,
        battle_format=formato,
        team=None,
        accept_open_team_sheet=True,
        start_listening=True,
    )


async def main():
    backend_url = os.getenv("BACKEND_WS_URL", "ws://localhost:3000/ws")
    bot_key = os.getenv("JWT_SECRET", "porybot_super_secret_key_changeme_in_production")
    ws_url = f"{backend_url}?bot_key={bot_key}"

    while True:
        print(f"[Launcher] Arrancando bot...")
        bot = crear_bot(FORMATO_DEFAULT)
        formato_actual = FORMATO_DEFAULT
        ultimo_combate["tiempo"] = time.time()
        ultimo_combate["en_combate"] = False

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
                                    nick      = data.get("nick")
                                    reg       = data.get("regulation", "regf")
                                    paste     = data.get("paste")
                                    formato   = FORMATO_POR_ARG.get(reg, FORMATO_DEFAULT)

                                    if formato != formato_actual:
                                        print(f"[Launcher] Cambiando regulación: {formato_actual} → {formato}")
                                        bot._format = formato
                                        bot._system_prompt = SYSTEM_PROMPT_POR_FORMATO.get(formato, SYSTEM_PROMPT_REGF)
                                        formato_actual = formato
                                    else:
                                        bot._format = formato

                                    if paste:
                                        bot._team = ConstantTeambuilder(paste)
                                        print(f"[Launcher] Equipo de la BD cargado para {nick}")
                                    else:
                                        bot._team = None

                                    ultimo_combate["tiempo"] = time.time()
                                    ultimo_combate["en_combate"] = True
                                    print(f"[Launcher] Desafiando a {nick} en formato {formato}")
                                    await bot.send_challenges(nick, 1)
                                    ultimo_combate["en_combate"] = False
                                    ultimo_combate["tiempo"] = time.time()

                            except Exception as e:
                                print(f"[Launcher] Error procesando mensaje: {e}")
                                ultimo_combate["en_combate"] = False

                except Exception as e:
                    print(f"[Launcher] Backend WS desconectado: {e}. Reconectando en 5s...")
                    await asyncio.sleep(5)

        async def watchdog():
            """Reinicia el bot si lleva más de 10 min en un combate sin terminar."""
            while True:
                await asyncio.sleep(60)
                if ultimo_combate["en_combate"]:
                    minutos = (time.time() - ultimo_combate["tiempo"]) / 60
                    if minutos > 10:
                        print(f"[Watchdog] ⚠️ Bot colgado {minutos:.0f} min — reiniciando...")
                        raise Exception("Watchdog timeout")
                else:
                    print(f"[Watchdog] Bot OK — en espera")

        try:
            await asyncio.gather(
                bot.accept_challenges(None, 100),
                escuchar_backend(),
                watchdog(),
            )
        except Exception as e:
            print(f"[Launcher] Reiniciando bot por: {e}")
            await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())