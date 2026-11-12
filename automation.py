# -*- coding: utf-8 -*-
"""
Motor de automação Microsoft Rewards via Microsoft Edge nativo (CDP - Chrome DevTools Protocol).
Calibrado via Diagnóstico de DOM real do Novo Microsoft Rewards (2026):
1. Faz login na conta Microsoft e aguarda carregar o painel (https://rewards.bing.com/dashboard).
2. Executa as Missões Reais sem cair/travar em telas de explicação:
   - Ignora <button> sem href (que são apenas modais explicativos de 'Saiba mais' / 'Como ativar').
   - Em /dashboard e /earn: localiza todos os cards <a href*='bing.com'> com '+5', '+10', '+15', '+20', '+30', '+50'
     que ainda NÃO tenham o status 'Concluído', clica fisicamente neles, aguarda 7s na aba do Bing (respondendo quiz/enquete se houver) e fecha a aba.
   - Na missão 'Veja o seu novo dashboard' (+95): clica em 'Ganhe agora' (/earn), 'Saiba mais' (/about?section=benefits) e 'Concluir agora' (/dashboard?section=dailyset),
     interage por 7s em cada tela destino e SEMPRE retorna ao fluxo principal (nunca fica preso na tela de explicação /about!).
3. Verifica a cota de 'Pesquisa do Bing' no Detalhamento de Pontos antes de iniciar pesquisas de teclado.
"""

import base64
import json
import os
import random
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from search_terms import gerar_lista_pesquisas, obter_pesquisa_para_missao


@dataclass
class AutomationConfig:
    email: str = ""
    senha: str = ""
    quantidade_pesquisas: int = 30
    tempo_pagina_segundos: float = 7.0         # Tempo permanecendo na página da missão/pesquisa (padrão 7s)
    intervalo_teclado_segundos: float = 10.0   # Intervalo entre uma pesquisa via teclado e outra (padrão 10s)
    atraso_tecla_ms: int = 85                  # Velocidade média por tecla em ms
    usar_variacao_humana: bool = True          # Adiciona pequena variação (+0.4s a +1.9s) para parecer humano
    espaco_final_pesquisa: bool = True         # Digita um espaço no final do termo antes de pesquisar
    clicar_resultado_pesquisa: bool = True     # Interage/rola na página aberta durante os 7s
    executar_cards_diarios: bool = True        # Faz todas as missões do painel Rewards (/dashboard, /earn e Novo Dashboard)
    executar_pesquisas_bing: bool = True       # Executa pesquisas no teclado (pula automaticamente se já estiver 15/15 concluído)
    debug_port: int = 9234
    perfil_dir: str = field(default_factory=lambda: os.path.abspath("./perfil_navegador"))

    def __post_init__(self):
        if not self.email or not self.senha:
            try:
                if os.path.exists("config_painel.json"):
                    with open("config_painel.json", "r", encoding="utf-8") as f:
                        dados = json.load(f)
                    if not self.email:
                        self.email = dados.get("email", "")
                    if not self.senha:
                        self.senha = dados.get("senha", "")
            except Exception:
                pass


@dataclass
class ActionReport:
    horario: str
    acao: str
    etapa: str
    status: str  # "SUCESSO", "ERRO", "AVISO", "INFO"
    duracao_s: float
    motivo: str


class SimpleWebSocketCDP:
    """Cliente WebSocket leve (RFC 6455) usando apenas biblioteca padrão do Python, com reconexão automática."""

    def __init__(self, ws_url: str, timeout: float = 15.0):
        self.ws_url = ws_url
        self.timeout = timeout
        parsed = urlparse(ws_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 9234
        self.path = parsed.path or "/"
        self._msg_id = 0
        self.sock: Optional[socket.socket] = None
        self._conectar()

    def _conectar(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._handshake()

    def _handshake(self):
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("utf-8"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise ConnectionError("Conexão fechada durante handshake WebSocket com o navegador.")
            response += chunk
        if b"101" not in response.split(b"\r\n")[0]:
            raise ConnectionError(f"Falha no handshake WebSocket CDP: {response[:120]!r}")

    def send_command(self, method: str, params: Optional[dict] = None, timeout: float = 12.0) -> dict:
        ultima_exc = None
        for tentativa in range(2):
            try:
                self._msg_id += 1
                cmd_id = self._msg_id
                payload = json.dumps({"id": cmd_id, "method": method, "params": params or {}}).encode("utf-8")
                self._send_frame(payload)

                self.sock.settimeout(timeout)
                deadline = time.time() + timeout
                while time.time() < deadline:
                    msg = self._recv_frame()
                    if not msg:
                        continue
                    data = json.loads(msg)
                    if data.get("id") == cmd_id:
                        if "error" in data:
                            raise RuntimeError(data["error"].get("message", str(data["error"])))
                        return data.get("result", {})
                raise TimeoutError(f"Tempo limite excedido aguardando resposta do navegador para '{method}'.")
            except (ConnectionError, OSError, TimeoutError) as exc:
                ultima_exc = exc
                if tentativa == 0 and method != "Browser.close":
                    try:
                        time.sleep(0.4)
                        self._conectar()
                        continue
                    except Exception:
                        pass
                raise ultima_exc
        raise ultima_exc

    def _send_frame(self, data: bytes):
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))

        mask = os.urandom(4)
        header.extend(mask)
        masked = bytearray(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(header + masked)

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("A aba do navegador foi fechada ou desconectada.")
            buf.extend(chunk)
        return bytes(buf)

    def _recv_frame(self) -> str:
        b1, b2 = self._recv_exact(2)
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length)
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        if opcode == 0x8:
            raise ConnectionError("Conexão encerrada pelo navegador.")
        if opcode == 0x9:
            self._send_pong(payload)
            return ""
        return payload.decode("utf-8", errors="replace")

    def _send_pong(self, payload: bytes):
        header = bytearray([0x8A, 0x80 | len(payload)])
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytearray(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + masked)

    def evaluate(self, expression: str, timeout: float = 10.0) -> Any:
        res = self.send_command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            timeout=timeout,
        )
        if "exceptionDetails" in res:
            detalhe = res["exceptionDetails"].get("text", "Erro JS")
            raise RuntimeError(f"Erro na página: {detalhe}")
        return res.get("result", {}).get("value")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def localizar_executavel_edge() -> Optional[str]:
    candidatos = [
        shutil.which("msedge"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in candidatos:
        if c and os.path.exists(c):
            return c
    return None


class RewardsAutomationEngine:
    """Executa o fluxo: 1) Login Microsoft -> 2) Todas as Missões do Novo Dashboard Rewards -> 3) Pesquisas Bing."""

    def __init__(
        self,
        on_report: Callable[[ActionReport], None],
        on_status_change: Callable[[str], None],
        on_progress: Callable[[int, int, int, int], None],
    ):
        self.on_report = on_report
        self.on_status_change = on_status_change
        self.on_progress = on_progress
        self._stop_event = threading.Event()
        self._running = False

        self.pesquisas_concluidas = 0
        self.cards_concluidos = 0
        self.erros_contagem = 0
        self.total_meta = 0
        self._ultimo_mouse_x = 450
        self._ultimo_mouse_y = 300

    @property
    def is_running(self) -> bool:
        return self._running

    def stop(self):
        """Solicita parada segura da automação."""
        self._stop_event.set()
        self.on_status_change("Parando...")

    def _emit(self, acao: str, etapa: str, status: str, duracao: float, motivo: str):
        if status == "ERRO":
            self.erros_contagem += 1
        report = ActionReport(
            horario=datetime.now().strftime("%H:%M:%S"),
            acao=acao,
            etapa=etapa,
            status=status,
            duracao_s=round(duracao, 1),
            motivo=motivo,
        )
        self.on_report(report)
        self.on_progress(
            self.pesquisas_concluidas,
            self.total_meta,
            self.cards_concluidos,
            self.erros_contagem,
        )

    def _sleep_interruptible(self, seconds: float) -> bool:
        end_time = time.time() + max(0.05, seconds)
        while time.time() < end_time:
            if self._stop_event.is_set():
                return False
            time.sleep(0.12)
        return True

    def _calcular_tempo(self, base: float, usar_variacao: bool) -> float:
        if not usar_variacao:
            return round(base, 1)
        return round(base + random.uniform(0.4, 1.9), 1)

    # -------------------------------------------------------------------------
    # Gerenciamento de Abas e Conexão CDP
    # -------------------------------------------------------------------------
    def _iniciar_edge_cdp(
        self, config: AutomationConfig, url_inicial: str
    ) -> tuple[Optional[subprocess.Popen], SimpleWebSocketCDP, str]:
        os.makedirs(config.perfil_dir, exist_ok=True)
        edge_bin = localizar_executavel_edge()
        if not edge_bin:
            raise FileNotFoundError("Microsoft Edge ou Google Chrome não encontrado no computador.")

        proc = None
        if not self._porta_cdp_ativa(config.debug_port):
            args = [
                edge_bin,
                f"--remote-debugging-port={config.debug_port}",
                f"--user-data-dir={config.perfil_dir}",
                "--remote-allow-origins=*",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                url_inicial,
            ]
            proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        deadline = time.time() + 15.0
        ws_url = None
        target_id = ""
        while time.time() < deadline:
            targets = self._listar_abas_cdp(config.debug_port)
            for t in targets:
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    ws_url = t["webSocketDebuggerUrl"]
                    target_id = t.get("id", "")
                    break
            if ws_url:
                break
            time.sleep(0.35)

        if not ws_url:
            raise ConnectionError(
                f"Não foi possível conectar ao Microsoft Edge na porta {config.debug_port}. "
                "Feche outras janelas do Edge abertas e tente novamente."
            )

        cdp = SimpleWebSocketCDP(ws_url)
        try:
            cdp.send_command("Page.bringToFront")
        except Exception:
            pass
        return proc, cdp, target_id

    def _caminho_cache_diario(self, config: AutomationConfig) -> str:
        os.makedirs(config.perfil_dir, exist_ok=True)
        return os.path.join(config.perfil_dir, "tarefas_concluidas_hoje.json")

    def _carregar_tarefas_concluidas_hoje(self, config: AutomationConfig) -> set[str]:
        hoje = datetime.now().strftime("%Y-%m-%d")
        caminho = self._caminho_cache_diario(config)
        try:
            if os.path.exists(caminho):
                with open(caminho, "r", encoding="utf-8") as f:
                    dados = json.load(f)
                if dados.get("data") == hoje and dados.get("email") == config.email:
                    return set(dados.get("chaves", []))
        except Exception:
            pass
        return set()

    def _salvar_tarefa_concluida_hoje(self, config: AutomationConfig, chave: str):
        hoje = datetime.now().strftime("%Y-%m-%d")
        caminho = self._caminho_cache_diario(config)
        atuais = self._carregar_tarefas_concluidas_hoje(config)
        atuais.add(chave)
        try:
            with open(caminho, "w", encoding="utf-8") as f:
                json.dump(
                    {"data": hoje, "email": config.email, "chaves": sorted(list(atuais))},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception:
            pass

    def _fechar_navegador_limpo(self, cdp: Optional[SimpleWebSocketCDP], proc: Optional[subprocess.Popen]):
        if cdp:
            try:
                cdp.send_command("Browser.close", timeout=3.0)
            except Exception:
                pass
            cdp.close()
        if proc:
            try:
                proc.wait(timeout=4.0)
            except Exception:
                if proc.poll() is None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass

    def _porta_cdp_ativa(self, port: int) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _listar_abas_cdp(self, port: int) -> list[dict]:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2.5) as resp:
                abas = json.loads(resp.read().decode("utf-8"))
                return [a for a in abas if a.get("type") == "page"]
        except Exception:
            return []

    def _ativar_aba_cdp(self, port: int, target_id: str):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/activate/{target_id}", timeout=2.0).read()
        except Exception:
            pass

    def _fechar_aba_cdp(self, port: int, target_id: str):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/close/{target_id}", timeout=2.0).read()
        except Exception:
            pass

    def _navegar_e_aguardar(self, cdp: SimpleWebSocketCDP, url: str, timeout: float = 20.0):
        cdp.send_command("Page.navigate", {"url": url}, timeout=timeout)
        self._aguardar_documento_pronto(cdp, timeout=timeout)

    def _aguardar_documento_pronto(self, cdp: SimpleWebSocketCDP, timeout: float = 15.0):
        deadline = time.time() + timeout
        time.sleep(0.5)
        while time.time() < deadline:
            if self._stop_event.is_set():
                return
            try:
                estado = cdp.evaluate("document.readyState")
                if estado in ("interactive", "complete"):
                    return
            except Exception:
                pass
            time.sleep(0.25)

    def _obter_pontos_atuais_rewards(self, cdp: SimpleWebSocketCDP) -> Optional[int]:
        """Lê o contador de pontos no topo do painel Rewards (ex: 976) para comprovar os ganhos."""
        try:
            val = cdp.evaluate("""
            (() => {
                const btns = Array.from(document.querySelectorAll("button, a, span"));
                for (const b of btns) {
                    const r = b.getBoundingClientRect();
                    if (r.top >= 0 && r.top < 80 && r.left > 900) {
                        const txt = (b.innerText || "").replace(/\\./g, "").replace(/,/g, "").trim();
                        if (/^\\d{2,7}$/.test(txt)) return parseInt(txt, 10);
                    }
                }
                return null;
            })()
            """)
            return int(val) if val is not None else None
        except Exception:
            return None

    # -------------------------------------------------------------------------
    # Simulação Física de Mouse e Teclado (Eventos isTrusted = true)
    # -------------------------------------------------------------------------
    def _mover_e_clicar_mouse(self, cdp: SimpleWebSocketCDP, x: float, y: float):
        passos = random.randint(4, 7)
        start_x, start_y = self._ultimo_mouse_x, self._ultimo_mouse_y
        for i in range(1, passos + 1):
            ix = int(start_x + (x - start_x) * (i / passos) + random.uniform(-2, 2))
            iy = int(start_y + (y - start_y) * (i / passos) + random.uniform(-2, 2))
            cdp.send_command(
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": max(1, ix), "y": max(1, iy), "button": "none"},
            )
            time.sleep(random.uniform(0.015, 0.035))

        fx, fy = max(1, int(x)), max(1, int(y))
        self._ultimo_mouse_x, self._ultimo_mouse_y = fx, fy

        cdp.send_command(
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": fx, "y": fy, "button": "left", "clickCount": 1},
        )
        time.sleep(random.uniform(0.055, 0.115))
        cdp.send_command(
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": fx, "y": fy, "button": "left", "clickCount": 1},
        )

    def _rolar_mouse_humano(self, cdp: SimpleWebSocketCDP, delta_y: int):
        try:
            cdp.send_command(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseWheel",
                    "x": self._ultimo_mouse_x,
                    "y": self._ultimo_mouse_y,
                    "deltaX": 0,
                    "deltaY": delta_y,
                },
            )
        except Exception:
            try:
                cdp.evaluate(f"window.scrollBy({{ top: {delta_y}, behavior: 'smooth' }});")
            except Exception:
                pass

    def _enviar_tecla_char(self, cdp: SimpleWebSocketCDP, ch: str):
        vk = ord(ch.upper()) if ch.isalpha() or ch.isdigit() else (32 if ch == " " else 0)
        code = f"Key{ch.upper()}" if ch.isalpha() else ("Space" if ch == " " else "")

        cdp.send_command(
            "Input.dispatchKeyEvent",
            {
                "type": "rawKeyDown",
                "windowsVirtualKeyCode": vk,
                "nativeVirtualKeyCode": vk,
                "key": ch,
                "code": code,
            },
        )
        cdp.send_command(
            "Input.dispatchKeyEvent",
            {
                "type": "char",
                "windowsVirtualKeyCode": vk,
                "key": ch,
                "code": code,
                "text": ch,
                "unmodifiedText": ch,
            },
        )
        cdp.send_command(
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "windowsVirtualKeyCode": vk,
                "nativeVirtualKeyCode": vk,
                "key": ch,
                "code": code,
            },
        )

    def _enviar_tecla_especial(self, cdp: SimpleWebSocketCDP, key: str, code: str, vk: int, modifiers: int = 0):
        cdp.send_command(
            "Input.dispatchKeyEvent",
            {
                "type": "rawKeyDown",
                "windowsVirtualKeyCode": vk,
                "nativeVirtualKeyCode": vk,
                "key": key,
                "code": code,
                "modifiers": modifiers,
            },
        )
        if key == "Enter":
            cdp.send_command(
                "Input.dispatchKeyEvent",
                {
                    "type": "char",
                    "windowsVirtualKeyCode": 13,
                    "key": "Enter",
                    "code": "Enter",
                    "text": "\r",
                    "unmodifiedText": "\r",
                },
            )
        time.sleep(0.04)
        cdp.send_command(
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "windowsVirtualKeyCode": vk,
                "nativeVirtualKeyCode": vk,
                "key": key,
                "code": code,
                "modifiers": modifiers,
            },
        )

    def _limpar_campo_com_teclado(self, cdp: SimpleWebSocketCDP):
        self._enviar_tecla_especial(cdp, "a", "KeyA", 65, modifiers=2)
        time.sleep(random.uniform(0.08, 0.16))
        self._enviar_tecla_especial(cdp, "Backspace", "Backspace", 8)
        time.sleep(random.uniform(0.12, 0.25))

    def _digitar_texto_humano(self, cdp: SimpleWebSocketCDP, texto: str, delay_base_ms: int):
        for ch in texto:
            if self._stop_event.is_set():
                break
            self._enviar_tecla_char(cdp, ch)
            jitter = random.randint(-20, 40)
            delay_s = max(0.035, (delay_base_ms + jitter) / 1000.0)
            time.sleep(delay_s)

    def _simular_permanencia_humana(
        self, cdp: SimpleWebSocketCDP, segundos: float, interagir_pagina: bool = False
    ) -> bool:
        inicio = time.time()
        metade = segundos / 2.0

        if not self._sleep_interruptible(min(1.2, segundos * 0.2)):
            return False

        self._rolar_mouse_humano(cdp, random.randint(280, 480))

        if not self._sleep_interruptible(max(0.2, metade - 1.2)):
            return False

        self._rolar_mouse_humano(cdp, random.randint(300, 520))

        restante = segundos - (time.time() - inicio)
        if restante > 0:
            if not self._sleep_interruptible(restante):
                return False

        self._rolar_mouse_humano(cdp, -750)
        try:
            cdp.evaluate("window.scrollTo({ top: 0, behavior: 'smooth' });")
        except Exception:
            pass
        return True

    def _verificar_bloqueio_ou_captcha(self, cdp: SimpleWebSocketCDP) -> Optional[str]:
        js_check = """
        (() => {
            const url = (window.location.href || '').toLowerCase();
            if (url.includes('captcha') || url.includes('challenge')) {
                return 'Desafio de segurança/CAPTCHA detectado (' + window.location.href + '). Complete manualmente no navegador.';
            }
            const hasCaptcha = document.querySelector("iframe[src*='captcha'], iframe[src*='turnstile'], #id_captcha, #b_captcha");
            if (hasCaptcha && hasCaptcha.offsetParent !== null) {
                return 'CAPTCHA visível na página. Resolva manualmente no navegador aberto.';
            }
            return null;
        })()
        """
        try:
            return cdp.evaluate(js_check)
        except Exception:
            return None

    # -------------------------------------------------------------------------
    # ETAPA 1: Login Automático na Conta Microsoft -> Redirecionamento ao Rewards
    # -------------------------------------------------------------------------
    def _realizar_login_microsoft_e_abrir_rewards(
        self, cdp: SimpleWebSocketCDP, config: AutomationConfig
    ) -> bool:
        t0 = time.time()
        self.on_status_change("Etapa 1: Verificando Login na Conta Microsoft...")

        # Aguarda a aba inicial estabilizar antes de verificar ou navegar (evita abortar conexão no startup)
        self._sleep_interruptible(2.5)
        self._aguardar_documento_pronto(cdp, timeout=15.0)
        url_atual_ini = (cdp.evaluate("window.location.href") or "").lower()
        if "rewards.bing.com" not in url_atual_ini and "login.live.com" not in url_atual_ini:
            try:
                self._navegar_e_aguardar(cdp, "https://rewards.bing.com/dashboard", timeout=22.0)
                self._sleep_interruptible(2.2)
            except Exception as exc:
                self._emit(
                    "Login Microsoft",
                    "Abertura da Página de Login",
                    "ERRO",
                    time.time() - t0,
                    f"Não foi possível carregar o painel do Rewards: {exc}",
                )
                return False

        deadline = time.time() + 45.0
        email_preenchido = False
        senha_preenchida = False

        while time.time() < deadline and not self._stop_event.is_set():
            estado = cdp.evaluate("""
            (() => {
                const url = (window.location.href || '').toLowerCase();
                const visivel = (el) => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 10 && r.height > 10 && window.getComputedStyle(el).visibility !== 'hidden';
                };
                const coords = (el) => {
                    const r = el.getBoundingClientRect();
                    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                };

                if (url.includes('rewards.bing.com') && !url.includes('signin') && !url.includes('login')) {
                    const btnEntrarRewards = document.querySelector("#raf-signin-link-id, a[href*='/signin'], a[data-bi-id*='signin']");
                    if (visivel(btnEntrarRewards)) {
                        return { tela: 'REWARDS_DESLOGADO', btn: coords(btnEntrarRewards) };
                    }
                    const textoBody = (document.body ? document.body.innerText : '').toLowerCase();
                    if (
                        textoBody.includes('painel de controle') ||
                        textoBody.includes('ganhar') ||
                        textoBody.includes('resgatar') ||
                        document.querySelector("a[href='/earn'], a[href='/dashboard'], mee-card, .ds-card-sec")
                    ) {
                        return { tela: 'REWARDS_LOGADO' };
                    }
                }

                const inputEmail = document.querySelector("input[type='email'], input[name='loginfmt'], #i0116, #usernameEntry");
                if (visivel(inputEmail)) {
                    const btnNext = document.querySelector("#idSIButton9, button[type='submit'], input[type='submit'], [data-testid='primaryButton']");
                    return {
                        tela: 'TELA_EMAIL',
                        input: coords(inputEmail),
                        btn: visivel(btnNext) ? coords(btnNext) : null
                    };
                }

                const linkUsarSenha = Array.from(document.querySelectorAll("a, button, div[role='button'], span")).find(el => {
                    if (!visivel(el)) return false;
                    const txt = (el.innerText || '').toLowerCase();
                    return (
                        el.id === 'idA_PWD_SwitchToPassword' ||
                        txt.includes('usar sua senha') ||
                        txt.includes('use your password') ||
                        txt.includes('digitar senha') ||
                        txt.includes('enter password')
                    );
                });

                const inputSenha = document.querySelector("input[type='password'], input[name='passwd'], #i0118, #passwordEntry");
                if (visivel(inputSenha)) {
                    const btnSign = document.querySelector("#idSIButton9, button[type='submit'], input[type='submit'], [data-testid='primaryButton']");
                    return {
                        tela: 'TELA_SENHA',
                        input: coords(inputSenha),
                        btn: visivel(btnSign) ? coords(btnSign) : null
                    };
                }

                if (linkUsarSenha) {
                    return { tela: 'ALTERNAR_PARA_SENHA', btn: coords(linkUsarSenha) };
                }

                const btnAceitar = document.querySelector("#acceptButton, #idSIButton9, [data-testid='primaryButton']");
                const btnNao = document.querySelector("#declineButton, #idBtn_Back, [data-testid='secondaryButton']");
                const textoPagina = (document.body ? document.body.innerText : '').toLowerCase();
                if (visivel(btnAceitar) && (visivel(btnNao) || textoPagina.includes('conectado') || textoPagina.includes('signed in'))) {
                    return { tela: 'CONTINUAR_CONECTADO', btn: coords(btnAceitar) };
                }

                const erroLogin = document.querySelector("#passwordError, #usernameError, [role='alert']");
                if (visivel(erroLogin) && (erroLogin.innerText || '').trim().length > 3) {
                    return { tela: 'ERRO_CREDENCIAIS', msg: (erroLogin.innerText || '').trim() };
                }

                return { tela: 'CARREGANDO', url: url };
            })()
            """) or {"tela": "CARREGANDO"}

            tela = estado.get("tela")

            if tela == "REWARDS_LOGADO":
                pts = self._obter_pontos_atuais_rewards(cdp)
                info_pts = f" (Saldo atual: {pts} pontos)" if pts is not None else ""
                self._emit(
                    "Login Microsoft",
                    "Autenticação Concluída",
                    "SUCESSO",
                    time.time() - t0,
                    f"Conta '{config.email}' autenticada e Dashboard do Rewards aberto{info_pts}.",
                )
                return True

            if tela == "REWARDS_DESLOGADO" and estado.get("btn"):
                self.on_status_change("Clicando em 'Entrar' no painel do Rewards...")
                self._mover_e_clicar_mouse(cdp, estado["btn"]["x"], estado["btn"]["y"])
                self._sleep_interruptible(2.5)
                continue

            if tela == "TELA_EMAIL" and not email_preenchido:
                if not config.email:
                    self._emit(
                        "Login Microsoft",
                        "Preenchimento de E-mail",
                        "ERRO",
                        time.time() - t0,
                        "O campo de e-mail está vazio nas configurações do Dashboard.",
                    )
                    return False

                self.on_status_change(f"Digitando e-mail ({config.email})...")
                self._mover_e_clicar_mouse(cdp, estado["input"]["x"], estado["input"]["y"])
                time.sleep(0.25)
                self._limpar_campo_com_teclado(cdp)
                self._digitar_texto_humano(cdp, config.email, config.atraso_tecla_ms)
                time.sleep(0.45)

                if estado.get("btn"):
                    self._mover_e_clicar_mouse(cdp, estado["btn"]["x"], estado["btn"]["y"])
                else:
                    self._enviar_tecla_especial(cdp, "Enter", "Enter", 13)

                email_preenchido = True
                self._emit(
                    "Login Microsoft",
                    "Etapa de E-mail",
                    "INFO",
                    time.time() - t0,
                    f"E-mail '{config.email}' digitado e enviado.",
                )
                self._sleep_interruptible(2.8)
                continue

            if tela == "ALTERNAR_PARA_SENHA" and estado.get("btn"):
                self.on_status_change("Selecionando opção 'Usar sua senha'...")
                self._mover_e_clicar_mouse(cdp, estado["btn"]["x"], estado["btn"]["y"])
                self._sleep_interruptible(2.0)
                continue

            if tela == "TELA_SENHA" and not senha_preenchida:
                if not config.senha:
                    self._emit(
                        "Login Microsoft",
                        "Preenchimento de Senha",
                        "ERRO",
                        time.time() - t0,
                        "A senha não foi informada no Dashboard.",
                    )
                    return False

                self.on_status_change("Digitando senha da conta Microsoft...")
                self._mover_e_clicar_mouse(cdp, estado["input"]["x"], estado["input"]["y"])
                time.sleep(0.25)
                self._limpar_campo_com_teclado(cdp)
                self._digitar_texto_humano(cdp, config.senha, config.atraso_tecla_ms)
                time.sleep(0.45)

                if estado.get("btn"):
                    self._mover_e_clicar_mouse(cdp, estado["btn"]["x"], estado["btn"]["y"])
                else:
                    self._enviar_tecla_especial(cdp, "Enter", "Enter", 13)

                senha_preenchida = True
                self._emit(
                    "Login Microsoft",
                    "Etapa de Senha",
                    "INFO",
                    time.time() - t0,
                    "Senha digitada e enviada. Aguardando confirmação de sessão...",
                )
                self._sleep_interruptible(3.2)
                continue

            if tela == "CONTINUAR_CONECTADO" and estado.get("btn"):
                self.on_status_change("Confirmando 'Continuar conectado? -> Sim'...")
                self._mover_e_clicar_mouse(cdp, estado["btn"]["x"], estado["btn"]["y"])
                self._sleep_interruptible(3.5)
                continue

            if tela == "ERRO_CREDENCIAIS":
                self._emit(
                    "Login Microsoft",
                    "Credenciais Recusadas",
                    "ERRO",
                    time.time() - t0,
                    f"A página de login retornou erro: {estado.get('msg')}",
                )
                return False

            time.sleep(0.8)

        url_final = (cdp.evaluate("window.location.href") or "").lower()
        if "rewards.bing.com" not in url_final:
            self._navegar_e_aguardar(cdp, "https://rewards.bing.com/dashboard", timeout=20.0)
            self._sleep_interruptible(3.0)

        return True

    # -------------------------------------------------------------------------
    # Modo 1: Abrir Perfil para Login Manual (Opcional)
    # -------------------------------------------------------------------------
    def abrir_perfil_para_login(self, config: AutomationConfig):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self.on_status_change("Realizando Login no Navegador...")

        t0 = time.time()
        proc = None
        cdp = None
        try:
            proc, cdp, _ = self._iniciar_edge_cdp(config, "https://rewards.bing.com/dashboard")
            self._realizar_login_microsoft_e_abrir_rewards(cdp, config)

            self._emit(
                "Sessão de Login",
                "Navegador Aberto",
                "INFO",
                time.time() - t0,
                "Verifique se o painel do Rewards está aberto na sua conta. Feche o navegador ou clique em 'Parar Execução' para salvar.",
            )

            while not self._stop_event.is_set():
                abas = self._listar_abas_cdp(config.debug_port)
                if not abas:
                    break
                time.sleep(0.6)

            self._emit(
                "Sessão de Login",
                "Sessão Salva",
                "SUCESSO",
                time.time() - t0,
                "Sessão salva com sucesso no perfil do navegador.",
            )
        except Exception as exc:
            self._emit(
                "Sessão de Login",
                "Falha ao Abrir Navegador",
                "ERRO",
                time.time() - t0,
                f"Não foi possível abrir ou conectar ao Microsoft Edge: {exc}",
            )
        finally:
            self._fechar_navegador_limpo(cdp, proc)
            self._running = False
            self.on_status_change("Parado")

    # -------------------------------------------------------------------------
    # Modo 2: Fluxo Completo (1. Loga -> 2. Identificador + Missões Reais -> 3. Pesquisas Bing)
    # -------------------------------------------------------------------------
    def executar_fluxo(self, config: AutomationConfig):
        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self.pesquisas_concluidas = 0
        self.cards_concluidos = 0
        self.erros_contagem = 0
        self.total_meta = config.quantidade_pesquisas
        self.on_progress(0, self.total_meta, 0, 0)
        self.on_status_change("Iniciando e fazendo Login...")

        proc = None
        cdp = None
        t_init = time.time()
        try:
            proc, cdp, rewards_tab_id = self._iniciar_edge_cdp(config, "https://rewards.bing.com/dashboard")
            logou_ok = self._realizar_login_microsoft_e_abrir_rewards(cdp, config)
            if not logou_ok or self._stop_event.is_set():
                return

            abas_atuais = self._listar_abas_cdp(config.debug_port)
            if abas_atuais:
                rewards_tab_id = abas_atuais[0].get("id", rewards_tab_id)

            # Passo 2: Identifica tarefas concluídas vs pendentes e executa APENAS as pendentes
            if config.executar_cards_diarios and not self._stop_event.is_set():
                self._executar_todas_missoes_no_rewards(cdp, rewards_tab_id, config)

            # Passo 3: Verifica no Identificador de Tarefas se as pesquisas do Bing já foram concluídas hoje!
            if config.executar_pesquisas_bing and not self._stop_event.is_set() and config.quantidade_pesquisas > 0:
                ja_concluidas, detalhe_cota = self._verificar_pesquisas_bing_ja_concluidas(cdp)
                if ja_concluidas:
                    self._emit(
                        "Identificador de Tarefas (Pesquisas)",
                        "Tarefa Já Completa — Ignorada",
                        "INFO",
                        0.5,
                        f"Identificado que '{detalhe_cota}' já está 100% completa hoje! Nenhuma pesquisa de teclado será feita.",
                    )
                else:
                    cdp = self._redirecionar_do_rewards_para_bing(cdp, rewards_tab_id, config)
                    self._executar_pesquisas_bing(cdp, config)

            # Passo 4: Volta ao Dashboard do Rewards no final e mostra a pontuação final
            if not self._stop_event.is_set():
                try:
                    self._navegar_e_aguardar(cdp, "https://rewards.bing.com/dashboard", timeout=15.0)
                    self._sleep_interruptible(2.8)
                    pts_finais = self._obter_pontos_atuais_rewards(cdp)
                    if pts_finais is not None:
                        self._emit(
                            "Resumo Final",
                            "Pontuação Atualizada no Rewards",
                            "SUCESSO",
                            1.0,
                            f"Fluxo concluído sem erros! Saldo atual no topo do Microsoft Rewards: {pts_finais} pontos.",
                        )
                except Exception:
                    pass

        except Exception as exc:
            self._emit(
                "Fluxo Principal",
                "Execução Geral",
                "ERRO",
                time.time() - t_init,
                f"Não foi possível concluir o fluxo principal: {exc}",
            )
        finally:
            self._fechar_navegador_limpo(cdp, proc)
            status_final = "Cancelado pelo Usuário" if self._stop_event.is_set() else "Concluído"
            self._running = False
            self.on_status_change(status_final)

    def _verificar_pesquisas_bing_ja_concluidas(self, cdp: SimpleWebSocketCDP) -> tuple[bool, str]:
        """
        Abre rapidamente o 'Detalhamento de pontos' em /earn (ou lê o texto da página)
        para verificar se 'Pesquisa do Bing' já atingiu o limite diário (ex: 15/15, 30/30, 90/90).
        """
        try:
            url_atual = (cdp.evaluate("window.location.href") or "").lower()
            if "/earn" not in url_atual:
                self._navegar_e_aguardar(cdp, "https://rewards.bing.com/earn", timeout=15.0)
                self._sleep_interruptible(2.5)

            pos_detalhe = cdp.evaluate("""
            (() => {
                const btns = Array.from(document.querySelectorAll("button"));
                const alvo = btns.find(b => (b.innerText || "").toLowerCase().includes("detalhamento de pontos"));
                if (!alvo) return null;
                alvo.scrollIntoView({ behavior: "instant", block: "center" });
                const r = alvo.getBoundingClientRect();
                return r.width > 20 ? { x: r.left + r.width / 2, y: r.top + r.height / 2 } : null;
            })()
            """)
            if pos_detalhe:
                self._mover_e_clicar_mouse(cdp, pos_detalhe["x"], pos_detalhe["y"])
                self._sleep_interruptible(1.8)

            texto_pagina = cdp.evaluate("document.body ? document.body.innerText : ''") or ""

            if pos_detalhe:
                self._enviar_tecla_especial(cdp, "Escape", "Escape", 27)
                time.sleep(0.5)

            padrao = re.search(
                r"pesquisa\s+do\s+bing[^\d]{0,30}(\d+)\s*/\s*(\d+)",
                texto_pagina,
                flags=re.IGNORECASE,
            )
            if padrao:
                atual = int(padrao.group(1))
                maximo = int(padrao.group(2))
                if maximo > 0 and atual >= maximo:
                    return True, f"Pesquisa do Bing: {atual}/{maximo} pontos"
        except Exception:
            pass
        return False, ""

    # -------------------------------------------------------------------------
    # ETAPA 2: Identificador de Tarefas + Execução APENAS de Tarefas Pendentes
    # -------------------------------------------------------------------------
    def _identificar_status_tarefas_pagina(
        self, cdp: SimpleWebSocketCDP, ja_tentadas: set[str], nome_aba: str
    ) -> dict:
        """
        IDENTIFICADOR DE TAREFAS:
        Escaneia a página atual (/dashboard ou /earn) e classifica todos os cards em:
        - 'concluidas': Cards que já exibem 'Concluído' / 'Completed' ou já foram feitos hoje.
        - 'pendentes': Cards clicáveis de pontos (+5, +10, +15, +20, +30, +50) ainda abertos.
        - 'tem_quest_novo_dashboard': True somente se a missão 'Veja o seu novo dashboard'
          ('onboarding_offer_punchcard') existir na página e NÃO estiver concluída!
          Isso evita navegar para uma oferta já concluída e gerar o aviso amarelo:
          'Esta oferta não está disponível para você'.
        """
        t0 = time.time()
        js = f"""
        (() => {{
            const ignorar = new Set({json.dumps(list(ja_tentadas))});
            const links = Array.from(document.querySelectorAll("a[href]"));
            const concluidas = [];
            const pendentes = [];
            let temQuestNovoDashboard = false;

            for (const a of links) {{
                if (a.closest("header, nav, footer")) continue;
                const r = a.getBoundingClientRect();
                if (r.width < 100 || r.height < 50) continue;

                const href = a.getAttribute("href") || "";
                const hrefLower = href.toLowerCase();
                const texto = (a.innerText || "").replace(/\\s+/g, " ").trim();
                const txtLower = texto.toLowerCase();

                // Verifica se o card da missão 'Veja o seu novo dashboard' está presente e aberto
                if (hrefLower.includes("onboarding_offer_punchcard")) {{
                    if (!txtLower.includes("concluído") && !txtLower.includes("4/4")) {{
                        temQuestNovoDashboard = true;
                    }} else {{
                        concluidas.push("Veja o seu novo dashboard (+95)");
                    }}
                    continue;
                }}

                // Ignora links de resgate, histórico, apps externos ou criação de papel de parede do Windows (form=airwpc)
                const ehCardRewardsDO = hrefLower.includes("publ=rewardsdo") || hrefLower.includes("form=ml");
                if (
                    hrefLower.includes("/redeem") ||
                    (!ehCardRewardsDO && (hrefLower.includes("referandearn") || hrefLower.includes("/refer"))) ||
                    hrefLower.includes("apps/wallpaper") ||
                    hrefLower.includes("form=airwpc") ||
                    txtLower.includes("definir como papel de parede") ||
                    hrefLower.includes("bingapp.microsoft.com") ||
                    hrefLower.includes("microsoft-edge://") ||
                    hrefLower.includes("xbox.com") ||
                    hrefLower.includes("spotify.com/legal")
                ) {{
                    continue;
                }}

                const apontaParaMissao = (
                    hrefLower.includes("bing.com/search") ||
                    hrefLower.includes("bing.com/spotlight") ||
                    ehCardRewardsDO
                );
                if (!apontaParaMissao) continue;

                const chave = ("BING_CARD|" + texto.slice(0, 50) + "|" + href.slice(0, 80)).toLowerCase();
                const tituloCurto = texto.slice(0, 48);

                // 1) Verifica se já está marcado como Concluído no DOM ou no cache diário
                if (txtLower.includes("concluído") || txtLower.includes("completed") || ignorar.has(chave)) {{
                    concluidas.push(tituloCurto);
                    continue;
                }}

                // 2) Verifica se possui selo de pontos pendentes (+5, +10, +15, etc.)
                const temPontos = (
                    /\\+\\s*(5|10|15|20|25|30|50|100)\\b/.test(texto) ||
                    /ganhe\\s+\\d+\\s+pontos/i.test(texto)
                );
                if (temPontos) {{
                    pendentes.push(tituloCurto);
                }}
            }}

            return {{
                concluidas: concluidas,
                pendentes: pendentes,
                temQuestNovoDashboard: temQuestNovoDashboard
            }};
        }})()
        """
        try:
            res = cdp.evaluate(js) or {"concluidas": [], "pendentes": [], "temQuestNovoDashboard": False}
        except Exception:
            res = {"concluidas": [], "pendentes": [], "temQuestNovoDashboard": False}

        concluidas = res.get("concluidas", [])
        pendentes = res.get("pendentes", [])

        if len(pendentes) == 0:
            resumo_concluidas = ", ".join(concluidas[:4]) + ("..." if len(concluidas) > 4 else "")
            self._emit(
                f"Identificador de Tarefas ({nome_aba})",
                "Todas as Tarefas Já Completas",
                "INFO",
                time.time() - t0,
                f"Identificadas {len(concluidas)} tarefa(s) já concluída(s) ({resumo_concluidas or 'nenhuma aberta'}) e 0 pendentes. Pulando sem repetir!",
            )
        else:
            self._emit(
                f"Identificador de Tarefas ({nome_aba})",
                f"{len(pendentes)} Pendente(s) | {len(concluidas)} Concluída(s)",
                "INFO",
                time.time() - t0,
                f"Encontradas {len(pendentes)} tarefa(s) pendente(s) para executar e {len(concluidas)} já concluída(s) (que serão ignoradas).",
            )

        return res

    def _coletar_cards_bing_pendentes_na_pagina(
        self, cdp: SimpleWebSocketCDP, ja_tentadas: set[str]
    ) -> Optional[dict]:
        """
        Localiza na página atual (/dashboard ou /earn) o próximo card REAL de pontos que ainda está PENDENTE.
        """
        js = f"""
        (() => {{
            const ignorar = new Set({json.dumps(list(ja_tentadas))});
            const links = Array.from(document.querySelectorAll("a[href]"));

            for (const a of links) {{
                if (a.closest("header, nav, footer")) continue;
                const r = a.getBoundingClientRect();
                if (r.width < 100 || r.height < 50) continue;

                const href = a.getAttribute("href") || "";
                const hrefLower = href.toLowerCase();
                const texto = (a.innerText || "").replace(/\\s+/g, " ").trim();
                const txtLower = texto.toLowerCase();

                // Se já está marcado como Concluído no texto do card, pula!
                if (txtLower.includes("concluído") || txtLower.includes("completed")) continue;

                const ehCardRewardsDO = hrefLower.includes("publ=rewardsdo") || hrefLower.includes("form=ml");
                if (
                    hrefLower.includes("/redeem") ||
                    (!ehCardRewardsDO && (hrefLower.includes("referandearn") || hrefLower.includes("/refer"))) ||
                    hrefLower.includes("apps/wallpaper") ||
                    hrefLower.includes("form=airwpc") ||
                    txtLower.includes("definir como papel de parede") ||
                    hrefLower.includes("bingapp.microsoft.com") ||
                    hrefLower.includes("microsoft-edge://") ||
                    hrefLower.includes("xbox.com") ||
                    hrefLower.includes("spotify.com/legal")
                ) {{
                    continue;
                }}

                const apontaParaMissao = (
                    hrefLower.includes("bing.com/search") ||
                    hrefLower.includes("bing.com/spotlight") ||
                    ehCardRewardsDO
                );
                const temPontos = (
                    /\\+\\s*(5|10|15|20|25|30|50|100)\\b/.test(texto) ||
                    /ganhe\\s+\\d+\\s+pontos/i.test(texto)
                );

                if (!apontaParaMissao || !temPontos) continue;

                const chave = ("BING_CARD|" + texto.slice(0, 50) + "|" + href.slice(0, 80)).toLowerCase();
                if (ignorar.has(chave)) continue;

                a.scrollIntoView({{ behavior: "instant", block: "center" }});
                const rc = a.getBoundingClientRect();
                return {{
                    chave: chave,
                    titulo: texto.slice(0, 58),
                    textoCompleto: texto,
                    href: href,
                    x: rc.left + rc.width / 2,
                    y: rc.top + rc.height / 2
                }};
            }}
            return null;
        }})()
        """
        try:
            return cdp.evaluate(js)
        except Exception:
            return None

    def _executar_cards_bing_da_aba(
        self,
        cdp: SimpleWebSocketCDP,
        rewards_tab_id: str,
        config: AutomationConfig,
        ja_tentadas: set[str],
        nome_aba_origem: str,
    ) -> bool:
        """
        Primeiro executa o IDENTIFICADOR DE TAREFAS na aba (/dashboard ou /earn).
        Se todas as tarefas já estiverem completas, retorna imediatamente sem clicar em nada!
        Retorna True se detectou a missão 'Veja o seu novo dashboard' aberta na página.
        """
        for _ in range(3):
            if self._stop_event.is_set():
                return False
            self._rolar_mouse_humano(cdp, 550)
            self._sleep_interruptible(0.5)
        self._rolar_mouse_humano(cdp, -1800)
        self._sleep_interruptible(0.7)

        diagnostico = self._identificar_status_tarefas_pagina(cdp, ja_tentadas, nome_aba_origem)
        tem_quest_onboard = bool(diagnostico.get("temQuestNovoDashboard"))

        if len(diagnostico.get("pendentes", [])) == 0:
            return tem_quest_onboard

        for _ in range(15):
            if self._stop_event.is_set():
                break

            card = self._coletar_cards_bing_pendentes_na_pagina(cdp, ja_tentadas)
            if not card:
                self._rolar_mouse_humano(cdp, 650)
                self._sleep_interruptible(0.7)
                card = self._coletar_cards_bing_pendentes_na_pagina(cdp, ja_tentadas)
                if not card:
                    break

            ja_tentadas.add(card["chave"])
            self._salvar_tarefa_concluida_hoje(config, card["chave"])
            titulo_curto = card["titulo"]
            nome_missao = f"[{nome_aba_origem}] {titulo_curto}"
            t_card = time.time()

            self.on_status_change(f"Clicando em {nome_missao}...")
            self._sleep_interruptible(0.4)

            abas_antes = {a["id"] for a in self._listar_abas_cdp(config.debug_port)}

            try:
                self._mover_e_clicar_mouse(cdp, card["x"], card["y"])
            except Exception as exc:
                self._emit(
                    nome_missao,
                    "Clique no Card",
                    "ERRO",
                    time.time() - t_card,
                    f"Não conseguiu clicar fisicamente no card: {exc}",
                )
                continue

            if not self._sleep_interruptible(2.0):
                break

            abas_depois = self._listar_abas_cdp(config.debug_port)
            novas_abas = [a for a in abas_depois if a["id"] not in abas_antes and a.get("webSocketDebuggerUrl")]
            tempo_permanencia = self._calcular_tempo(config.tempo_pagina_segundos, config.usar_variacao_humana)

            if novas_abas:
                nova_aba_info = novas_abas[-1]
                aba_id = nova_aba_info["id"]
                aba_ws = nova_aba_info["webSocketDebuggerUrl"]
                aba_cdp = None
                try:
                    self._ativar_aba_cdp(config.debug_port, aba_id)
                    aba_cdp = SimpleWebSocketCDP(aba_ws)
                    try:
                        aba_cdp.send_command("Page.bringToFront")
                    except Exception:
                        pass

                    self._aguardar_documento_pronto(aba_cdp, timeout=14.0)
                    self._garantir_login_sso_no_bing(aba_cdp)

                    detalhe = self._resolver_missao_na_aba_redirecionada(
                        aba_cdp, card["textoCompleto"], tempo_permanencia, config
                    )

                    self.cards_concluidos += 1
                    self._emit(
                        nome_missao,
                        "Card Concluído (+Pontos)",
                        "SUCESSO",
                        time.time() - t_card,
                        detalhe,
                    )
                except Exception as exc:
                    self._emit(
                        nome_missao,
                        "Aba Redirecionada",
                        "ERRO",
                        time.time() - t_card,
                        f"O card abriu nova aba, mas houve erro durante a permanência: {exc}",
                    )
                finally:
                    if aba_cdp:
                        aba_cdp.close()
                    self._fechar_aba_cdp(config.debug_port, aba_id)
                    self._ativar_aba_cdp(config.debug_port, rewards_tab_id)
                    try:
                        cdp.send_command("Page.bringToFront")
                    except Exception:
                        pass
            else:
                self._sleep_interruptible(tempo_permanencia)
                self.cards_concluidos += 1
                self._emit(
                    nome_missao,
                    "Clique no Card",
                    "SUCESSO",
                    time.time() - t_card,
                    f"Card acionado e aguardou {tempo_permanencia}s.",
                )

            self._sleep_interruptible(random.uniform(1.4, 2.4))

        return tem_quest_onboard

    def _executar_missao_veja_seu_novo_dashboard(
        self,
        cdp: SimpleWebSocketCDP,
        rewards_tab_id: str,
        config: AutomationConfig,
        ja_tentadas: set[str],
    ):
        """
        Executa a missão 'Veja o seu novo dashboard' (+95 pontos) SOMENTE se o Identificador de Tarefas
        confirmar que ela ainda está disponível no painel.
        """
        url_quest = "https://rewards.bing.com/earn/quest/WW_pcparent_redesign_existinguser_onboarding_offer_punchcard"
        t0 = time.time()
        self.on_status_change("Abrindo missão 'Veja o seu novo dashboard' (+95)...")

        try:
            self._navegar_e_aguardar(cdp, url_quest, timeout=18.0)
            if not self._sleep_interruptible(3.0):
                return
        except Exception as exc:
            self._emit(
                "Missão: Veja o seu novo dashboard",
                "Abertura da Missão",
                "AVISO",
                time.time() - t0,
                f"Não foi possível abrir a missão de boas-vindas: {exc}",
            )
            return

        for passo in range(4):
            if self._stop_event.is_set():
                break

            url_atual = (cdp.evaluate("window.location.href") or "").lower()
            if "onboarding_offer_punchcard" not in url_atual:
                # Se o Rewards redirecionou para /dashboard (oferta já concluída/indisponível), sai imediatamente!
                break

            subtarefa = cdp.evaluate(f"""
            (() => {{
                const ignorar = new Set({json.dumps(list(ja_tentadas))});
                const links = Array.from(document.querySelectorAll("a[href]"));
                for (const a of links) {{
                    if (a.closest("header, nav, footer")) continue;
                    const txt = (a.innerText || "").replace(/\\s+/g, " ").trim();
                    const txtLower = txt.toLowerCase();
                    const href = a.getAttribute("href") || "";

                    if (
                        txtLower === "concluir agora" ||
                        txtLower === "ganhe agora" ||
                        txtLower === "saiba mais"
                    ) {{
                        const chave = ("QUEST_ONBOARD|" + txtLower + "|" + href).toLowerCase();
                        if (ignorar.has(chave)) continue;

                        a.scrollIntoView({{ behavior: "instant", block: "center" }});
                        const r = a.getBoundingClientRect();
                        if (r.width > 20 && r.height > 15) {{
                            return {{
                                chave: chave,
                                textoBotao: txt,
                                href: href,
                                x: r.left + r.width / 2,
                                y: r.top + r.height / 2
                            }};
                        }}
                    }}
                }}
                return null;
            }})()
            """)

            if not subtarefa:
                break

            ja_tentadas.add(subtarefa["chave"])
            self._salvar_tarefa_concluida_hoje(config, subtarefa["chave"])
            botao_txt = subtarefa["textoBotao"]
            href_sub = subtarefa["href"]
            nome_sub = f"Novo Dashboard (+95): '{botao_txt}' ({href_sub})"
            t_sub = time.time()

            self.on_status_change(f"Clicando em '{botao_txt}' na missão Novo Dashboard...")
            self._mover_e_clicar_mouse(cdp, subtarefa["x"], subtarefa["y"])

            if not self._sleep_interruptible(3.0):
                break
            self._aguardar_documento_pronto(cdp, timeout=15.0)

            tempo_permanencia = self._calcular_tempo(config.tempo_pagina_segundos, config.usar_variacao_humana)
            url_destino = (cdp.evaluate("window.location.href") or "").lower()

            if "dailyset" in href_sub.lower() or "dashboard" in url_destino:
                self.on_status_change("Executando cards do Conjunto Diário...")
                self._executar_cards_bing_da_aba(cdp, rewards_tab_id, config, ja_tentadas, "Conjunto Diário")
            else:
                self.on_status_change(f"Explorando página '{href_sub}' por {tempo_permanencia}s para concluir a tarefa...")
                self._simular_permanencia_humana(cdp, tempo_permanencia, interagir_pagina=True)

            self.cards_concluidos += 1
            self._emit(
                nome_sub,
                "Sub-tarefa Executada",
                "SUCESSO",
                time.time() - t_sub,
                f"Clicou em '{botao_txt}', interagiu com a página '{url_destino[:50]}' por {tempo_permanencia}s e retornou.",
            )

            self._navegar_e_aguardar(cdp, url_quest, timeout=16.0)
            self._sleep_interruptible(2.2)

    def _executar_todas_missoes_no_rewards(
        self, cdp: SimpleWebSocketCDP, rewards_tab_id: str, config: AutomationConfig
    ):
        """
        Orquestra o Identificador de Tarefas + execução apenas do que estiver pendente:
        1) Aba 'Painel de Controle' (/dashboard): identifica concluídas vs pendentes e executa só as pendentes.
        2) Aba 'Ganhar' (/earn): identifica concluídas vs pendentes e executa só as pendentes.
        3) Missão 'Veja o seu novo dashboard' (+95): SÓ abre se o Identificador de Tarefas detectar que ela ainda existe na página!
        """
        ja_tentadas: set[str] = self._carregar_tarefas_concluidas_hoje(config)
        quest_onboard_disponivel = False

        # 1. Identifica e varre os cards do Painel de Controle (/dashboard)
        self.on_status_change("Etapa 2A: Identificando tarefas em 'Painel de Controle' (/dashboard)...")
        try:
            url_atual = (cdp.evaluate("window.location.href") or "").lower()
            if "/dashboard" not in url_atual:
                self._navegar_e_aguardar(cdp, "https://rewards.bing.com/dashboard", timeout=18.0)
                self._sleep_interruptible(2.8)
            tem_q1 = self._executar_cards_bing_da_aba(cdp, rewards_tab_id, config, ja_tentadas, "Painel de Controle")
            quest_onboard_disponivel = quest_onboard_disponivel or tem_q1
        except Exception as exc:
            self._emit(
                "Painel de Controle",
                "Identificador de Tarefas",
                "ERRO",
                1.0,
                f"Erro ao verificar /dashboard: {exc}",
            )

        if self._stop_event.is_set():
            return

        # 2. Identifica e varre todos os cards da aba Ganhar (/earn)
        self.on_status_change("Etapa 2B: Identificando tarefas na aba 'Ganhar' (/earn)...")
        try:
            self._navegar_e_aguardar(cdp, "https://rewards.bing.com/earn", timeout=18.0)
            self._sleep_interruptible(3.0)
            tem_q2 = self._executar_cards_bing_da_aba(cdp, rewards_tab_id, config, ja_tentadas, "Aba Ganhar")
            quest_onboard_disponivel = quest_onboard_disponivel or tem_q2
        except Exception as exc:
            self._emit(
                "Aba Ganhar",
                "Identificador de Tarefas",
                "ERRO",
                1.0,
                f"Erro ao verificar /earn: {exc}",
            )

        if self._stop_event.is_set():
            return

        # 3. Só abre "Veja o seu novo dashboard" (+95) se o Identificador de Tarefas viu que ela está disponível!
        if quest_onboard_disponivel:
            self._executar_missao_veja_seu_novo_dashboard(cdp, rewards_tab_id, config, ja_tentadas)
        else:
            self._emit(
                "Identificador de Tarefas (Missão +95)",
                "Missão 'Veja o seu novo dashboard' Já Concluída",
                "INFO",
                0.2,
                "Missão de boas-vindas (+95) já foi concluída anteriormente. Não será reaberta (evita aviso de 'Oferta não disponível').",
            )

    def _resolver_missao_na_aba_redirecionada(
        self,
        aba_cdp: SimpleWebSocketCDP,
        texto_missao: str,
        tempo_permanencia: float,
        config: AutomationConfig,
    ) -> str:
        """
        Dentro da aba do Bing aberta pelo clique no card:
        - Se houver Quiz (#rqStartQuiz / .rqOption / .btOptionCard / .wk_choice / #btoption0), responde as opções.
        - Permanece 7s rolando a página suavemente (sem apagar a query da missão!).
        """
        self._sleep_interruptible(1.5)

        interacao_quiz = aba_cdp.evaluate("""
        (() => {
            const visivel = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                return r.width > 10 && r.height > 10;
            };
            const coords = (el) => {
                el.scrollIntoView({ behavior: 'instant', block: 'center' });
                const r = el.getBoundingClientRect();
                return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
            };

            const btnStartQuiz = document.querySelector("#rqStartQuiz");
            if (visivel(btnStartQuiz)) {
                return { tipo: "START_QUIZ", pos: coords(btnStartQuiz) };
            }

            const opcoesPoll = document.querySelectorAll("#btoption0, #btoption1, .btOptionCard, .wk_choice, .rqOption");
            for (const op of opcoesPoll) {
                if (visivel(op)) {
                    return { tipo: "OPCAO_ENQUETE_OU_QUIZ", pos: coords(op) };
                }
            }
            return null;
        })()
        """)

        if interacao_quiz:
            tipo = interacao_quiz.get("tipo")
            pos = interacao_quiz.get("pos")
            if pos:
                self._mover_e_clicar_mouse(aba_cdp, pos["x"], pos["y"])
                self._sleep_interruptible(2.2)

                if tipo == "START_QUIZ" or "OPCAO" in str(tipo):
                    for _ in range(5):
                        if self._stop_event.is_set():
                            break
                        op_pos = aba_cdp.evaluate("""
                        (() => {
                            const op = document.querySelector(".rqOption, .btOptionCard, .wk_choice");
                            if (!op) return null;
                            const r = op.getBoundingClientRect();
                            if (r.width < 10) return null;
                            return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                        })()
                        """)
                        if not op_pos:
                            break
                        self._mover_e_clicar_mouse(aba_cdp, op_pos["x"], op_pos["y"])
                        self._sleep_interruptible(2.2)

            self._simular_permanencia_humana(aba_cdp, tempo_permanencia, interagir_pagina=True)
            return f"Quiz/Enquete respondido e permaneceu {tempo_permanencia}s na página da missão."

        self.on_status_change(f"Permanecendo {tempo_permanencia}s na página da missão...")
        self._simular_permanencia_humana(aba_cdp, tempo_permanencia, interagir_pagina=True)
        return f"Redirecionado para o Bing e permaneceu {tempo_permanencia}s na página da atividade."

    # -------------------------------------------------------------------------
    # ETAPA 3: Redirecionamento ao Bing e Pesquisas Gerais com Espaço
    # -------------------------------------------------------------------------
    def _redirecionar_do_rewards_para_bing(
        self, cdp: SimpleWebSocketCDP, rewards_tab_id: str, config: AutomationConfig
    ) -> SimpleWebSocketCDP:
        t0 = time.time()
        self.on_status_change("Saindo do Dashboard Rewards para o Bing...")

        try:
            pos_link_bing = cdp.evaluate("""
            (() => {
                window.scrollTo({ top: 0, behavior: 'instant' });
                const links = Array.from(document.querySelectorAll("a[href*='bing.com']"));
                const alvo = links.find(a => {
                    const r = a.getBoundingClientRect();
                    const href = (a.href || '').toLowerCase();
                    return r.width > 20 && r.height > 15 && !href.includes('rewards.bing.com');
                });
                if (!alvo) return null;
                alvo.scrollIntoView({ behavior: 'instant', block: 'center' });
                const r = alvo.getBoundingClientRect();
                return { x: r.left + r.width / 2, y: r.top + r.height / 2, href: alvo.href };
            })()
            """)

            if pos_link_bing:
                abas_antes = {a["id"] for a in self._listar_abas_cdp(config.debug_port)}
                self._mover_e_clicar_mouse(cdp, pos_link_bing["x"], pos_link_bing["y"])
                self._sleep_interruptible(2.2)

                abas_depois = self._listar_abas_cdp(config.debug_port)
                novas_abas = [a for a in abas_depois if a["id"] not in abas_antes and a.get("webSocketDebuggerUrl")]
                if novas_abas:
                    nova = novas_abas[-1]
                    self._ativar_aba_cdp(config.debug_port, nova["id"])
                    novo_cdp = SimpleWebSocketCDP(nova["webSocketDebuggerUrl"])
                    try:
                        novo_cdp.send_command("Page.bringToFront")
                    except Exception:
                        pass
                    self._aguardar_documento_pronto(novo_cdp, timeout=12.0)
                    self._emit(
                        "Redirecionamento Rewards → Bing",
                        "Clique no Dashboard Rewards",
                        "INFO",
                        time.time() - t0,
                        "Clicou no Dashboard do Rewards e foi redirecionado ao Bing em nova aba.",
                    )
                    return novo_cdp
        except Exception:
            pass

        try:
            cdp.evaluate("window.location.href = 'https://www.bing.com/?FORM=Z9FD1';")
            self._aguardar_documento_pronto(cdp, timeout=15.0)
            self._sleep_interruptible(2.0)
        except Exception:
            self._navegar_e_aguardar(cdp, "https://www.bing.com/?FORM=Z9FD1", timeout=15.0)

        return cdp

    def _garantir_login_sso_no_bing(self, cdp: SimpleWebSocketCDP):
        try:
            status_login = cdp.evaluate("""
            (() => {
                const id_n = document.querySelector('#id_n');
                const id_s = document.querySelector('#id_s, #id_a');
                const id_l = document.querySelector('#id_l');
                const points = document.querySelector('#id_rc, .points-container');
                const nomeUsuario = id_n ? (id_n.innerText || '').trim() : '';
                const textoEntrar = id_s ? (id_s.innerText || '').trim() : '';
                const precisaClicarEntrar = Boolean(
                    !nomeUsuario &&
                    id_l &&
                    id_s &&
                    id_s.offsetParent !== null &&
                    (textoEntrar.toLowerCase().includes('entrar') || textoEntrar.toLowerCase().includes('sign in'))
                );
                if (precisaClicarEntrar) {
                    const r = id_l.getBoundingClientRect();
                    return { logado: false, clicar: true, x: r.left + r.width / 2, y: r.top + r.height / 2 };
                }
                return {
                    logado: Boolean(nomeUsuario || points),
                    clicar: false,
                    usuario: nomeUsuario,
                    pontos: points ? (points.innerText || '').trim() : ''
                };
            })()
            """)
            if status_login and status_login.get("clicar"):
                self._emit(
                    "Autenticação no Bing",
                    "Vinculando Sessão no Bing (#id_l)",
                    "INFO",
                    0.5,
                    "Clicando em 'Entrar' no cabeçalho do Bing para sincronizar o login da conta Microsoft.",
                )
                self._mover_e_clicar_mouse(cdp, status_login["x"], status_login["y"])
                self._sleep_interruptible(3.5)
                self._aguardar_documento_pronto(cdp, timeout=12.0)
        except Exception:
            pass

    def _executar_pesquisas_bing(self, cdp: SimpleWebSocketCDP, config: AutomationConfig):
        termos = gerar_lista_pesquisas(config.quantidade_pesquisas)

        url_inicial = (cdp.evaluate("window.location.href") or "").lower()
        if "bing.com" not in url_inicial or "rewards.bing.com" in url_inicial:
            self._navegar_e_aguardar(cdp, "https://www.bing.com/?FORM=Z9FD1", timeout=20.0)
            self._sleep_interruptible(2.0)

        self._garantir_login_sso_no_bing(cdp)

        for idx, termo in enumerate(termos, start=1):
            if self._stop_event.is_set():
                break

            acao_label = f"Pesquisa {idx}/{config.quantidade_pesquisas}: '{termo[:32]}'"
            self.on_status_change(f"Digitando pesquisa ({idx}/{config.quantidade_pesquisas})...")
            t_inicio = time.time()

            try:
                url_atual = (cdp.evaluate("window.location.href") or "").lower()
                if "bing.com" not in url_atual or "rewards.bing.com" in url_atual:
                    self._navegar_e_aguardar(cdp, "https://www.bing.com/", timeout=15.0)
                    self._sleep_interruptible(1.2)
                    self._garantir_login_sso_no_bing(cdp)

                bloqueio = self._verificar_bloqueio_ou_captcha(cdp)
                if bloqueio:
                    self._emit(acao_label, "Bloqueio / CAPTCHA", "ERRO", time.time() - t_inicio, bloqueio)
                    if not self._sleep_interruptible(12.0):
                        break
                    continue

                pos_input = cdp.evaluate("""
                (() => {
                    window.scrollTo({ top: 0, behavior: 'instant' });
                    const el = document.querySelector("#sb_form_q, textarea[name='q'], input[name='q']");
                    if (!el) return null;
                    const r = el.getBoundingClientRect();
                    if (r.width < 10 || r.height < 10) return null;
                    return { x: r.left + r.width * 0.35, y: r.top + r.height / 2 };
                })()
                """)

                if not pos_input:
                    self._navegar_e_aguardar(cdp, "https://www.bing.com/", timeout=15.0)
                    self._sleep_interruptible(1.5)
                    pos_input = cdp.evaluate("""
                    (() => {
                        const el = document.querySelector("#sb_form_q, textarea[name='q'], input[name='q']");
                        if (!el) return null;
                        const r = el.getBoundingClientRect();
                        return { x: r.left + r.width * 0.35, y: r.top + r.height / 2 };
                    })()
                    """)

                if not pos_input:
                    self._emit(
                        acao_label,
                        "Localizar Barra de Busca",
                        "ERRO",
                        time.time() - t_inicio,
                        "Não encontrou a barra de pesquisa (#sb_form_q) na página do Bing.",
                    )
                    continue

                self._mover_e_clicar_mouse(cdp, pos_input["x"], pos_input["y"])
                time.sleep(random.uniform(0.2, 0.4))
                self._limpar_campo_com_teclado(cdp)

                cdp.evaluate("""
                (() => {
                    const el = document.querySelector("#sb_form_q, textarea[name='q'], input[name='q']");
                    if (el && el.value) {
                        el.value = '';
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                    if (el) el.focus();
                })()
                """)
                time.sleep(random.uniform(0.15, 0.3))

                for ch in termo:
                    if self._stop_event.is_set():
                        break
                    self._enviar_tecla_char(cdp, ch)
                    jitter = random.randint(-25, 45)
                    delay_s = max(0.035, (config.atraso_tecla_ms + jitter) / 1000.0)
                    time.sleep(delay_s)
                    if ch == " " and random.random() < 0.35:
                        time.sleep(random.uniform(0.08, 0.2))

                if self._stop_event.is_set():
                    break

                if config.espaco_final_pesquisa:
                    time.sleep(random.uniform(0.25, 0.45))
                    self._enviar_tecla_char(cdp, " ")
                    self.on_status_change(
                        f"Espaço pós-pesquisa digitado ({idx}/{config.quantidade_pesquisas})..."
                    )
                    time.sleep(random.uniform(0.85, 1.35))

                url_antes_enter = cdp.evaluate("window.location.href") or ""
                self._enviar_tecla_especial(cdp, "Enter", "Enter", 13)
                time.sleep(0.8)

                mudou_pagina = cdp.evaluate(
                    f"window.location.href !== {json.dumps(url_antes_enter)} && window.location.href.toLowerCase().includes('search?')"
                )
                if not mudou_pagina:
                    pos_lupa = cdp.evaluate("""
                    (() => {
                        const btn = document.querySelector("#sb_form_go, #search_icon, button[type='submit']");
                        if (!btn) return null;
                        const r = btn.getBoundingClientRect();
                        if (r.width > 5 && r.height > 5) {
                            return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                        }
                        return null;
                    })()
                    """)
                    if pos_lupa:
                        self._mover_e_clicar_mouse(cdp, pos_lupa["x"], pos_lupa["y"])
                    else:
                        self._enviar_tecla_especial(cdp, "Enter", "Enter", 13)

                carregou_resultados = False
                deadline_res = time.time() + 12.0
                while time.time() < deadline_res:
                    if self._stop_event.is_set():
                        break
                    ok = cdp.evaluate("""
                    (() => {
                        return Boolean(
                            document.querySelector('#b_results') &&
                            document.readyState === 'complete'
                        );
                    })()
                    """)
                    if ok:
                        carregou_resultados = True
                        break
                    time.sleep(0.3)

                if not carregou_resultados:
                    self._emit(
                        acao_label,
                        "Carregamento dos Resultados",
                        "ERRO",
                        time.time() - t_inicio,
                        "A pesquisa foi enviada, mas a página de resultados (#b_results) não terminou de carregar em 12s.",
                    )
                    continue

                tempo_pagina = self._calcular_tempo(config.tempo_pagina_segundos, config.usar_variacao_humana)
                self.on_status_change(
                    f"Permanecendo {tempo_pagina}s na pesquisa ({idx}/{config.quantidade_pesquisas})..."
                )

                if not self._simular_permanencia_humana(cdp, tempo_pagina, interagir_pagina=config.clicar_resultado_pesquisa):
                    break

                pontos_bing = cdp.evaluate("""
                (() => {
                    const el = document.querySelector('#id_rc, .points-container');
                    return el ? (el.innerText || '').trim() : '';
                })()
                """) or ""
                info_pontos = f" | Pontos no Bing: {pontos_bing}" if pontos_bing else ""

                self.pesquisas_concluidas += 1
                self._emit(
                    acao_label,
                    "Pesquisa + Espaço + 7s",
                    "SUCESSO",
                    time.time() - t_inicio,
                    f"Digitada com espaço final, resultados carregados e permaneceu {tempo_pagina}s na página{info_pontos}.",
                )

                if idx < len(termos) and not self._stop_event.is_set():
                    intervalo = self._calcular_tempo(config.intervalo_teclado_segundos, config.usar_variacao_humana)
                    self.on_status_change(
                        f"Intervalo de teclado: aguardando {intervalo}s ({idx}/{config.quantidade_pesquisas})..."
                    )
                    if not self._sleep_interruptible(intervalo):
                        break

            except ConnectionError as exc:
                self._emit(
                    acao_label,
                    "Conexão com o Navegador",
                    "ERRO",
                    time.time() - t_inicio,
                    f"A janela do navegador foi fechada durante a pesquisa: {exc}",
                )
                break
            except Exception as exc:
                self._emit(
                    acao_label,
                    "Execução da Pesquisa",
                    "ERRO",
                    time.time() - t_inicio,
                    f"Não foi possível concluir a pesquisa: {exc}",
                )
