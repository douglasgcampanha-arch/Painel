#!/usr/bin/env python3
"""
Servidor local do Painel (somente 127.0.0.1).

- GET  /                 -> painel.html (com o token de sessão injetado)
- GET  /api/astrea       -> estado da fila de envios ao Astrea
- POST /api/astrea/enviar-> enfileira um lançamento (tarefa/prazo) para o robô do Astrea

Proteções: escuta só em 127.0.0.1; confere o cabeçalho Host (contra DNS rebinding);
exige o cabeçalho X-Painel-Token (o token só existe na página servida aqui e outros sites
não conseguem lê-lo); não responde a pedidos CORS.
"""
from __future__ import annotations

import json
import secrets
import sys
import threading
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import djen_painel  # noqa: E402

DADOS = BASE / "dados"
ARQ_FILA = DADOS / "astrea_fila.json"
PAINEL = BASE / "painel.html"
TOKEN = secrets.token_urlsafe(32)
_trava = threading.Lock()
_evento = threading.Event()

CAMPOS = {"origem", "ref", "processo", "tipo", "titulo", "descricao", "data"}


def _ler_fila() -> list[dict]:
    try:
        return json.loads(ARQ_FILA.read_text(encoding="utf-8"))
    except Exception:
        return []


def _gravar_fila(fila: list[dict]) -> None:
    DADOS.mkdir(exist_ok=True)
    tmp = ARQ_FILA.with_suffix(".tmp")
    tmp.write_text(json.dumps(fila, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ARQ_FILA)


def _atualizar(item_id: str, **campos) -> None:
    with _trava:
        fila = _ler_fila()
        for it in fila:
            if it["id"] == item_id:
                it.update(campos)
        _gravar_fila(fila)


def trabalhador() -> None:
    """Processa a fila em sequência (um navegador por vez)."""
    while True:
        _evento.wait(timeout=60)
        _evento.clear()
        while True:
            with _trava:
                pend = next((i for i in _ler_fila() if i["status"] == "pendente"), None)
            if not pend:
                break
            _atualizar(pend["id"], status="enviando", atualizado_em=_agora())
            try:
                import astrea
                cfg = djen_painel.carregar_config()
                res = astrea.enviar(pend, cfg, djen_painel.log)
                _atualizar(pend["id"], status="enviado", resultado=res or "", erro="", atualizado_em=_agora())
                djen_painel.log(f"Astrea: lançado {pend['tipo']} do processo {pend['processo']}")
            except Exception as e:  # registra e segue para o próximo
                _atualizar(pend["id"], status="erro", erro=str(e)[:300], atualizado_em=_agora())
                djen_painel.log(f"Astrea: erro ao lançar {pend['processo']}: {e}")
                traceback.print_exc()


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Handler(BaseHTTPRequestHandler):
    server_version = "PainelLocal"

    def _host_ok(self) -> bool:
        porta = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{porta}", f"localhost:{porta}")

    def _json(self, codigo: int, dados) -> None:
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"erro": "host não permitido"})
        if self.path in ("/", "/index.html", "/painel.html"):
            try:
                html = PAINEL.read_text(encoding="utf-8")
            except FileNotFoundError:
                html = "<p>Painel ainda não gerado. Rode atualizar_agora.command.</p>"
            html = html.replace("/*__TOKEN__*/\"\"", json.dumps(TOKEN))
            corpo = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            return self.wfile.write(corpo)
        if self.path == "/api/astrea":
            if self.headers.get("X-Painel-Token") != TOKEN:
                return self._json(403, {"erro": "token inválido"})
            with _trava:
                return self._json(200, {"fila": _ler_fila()})
        return self._json(404, {"erro": "não encontrado"})

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Painel-Token") != TOKEN:
            return self._json(403, {"erro": "não autorizado"})
        if self.path != "/api/astrea/enviar":
            return self._json(404, {"erro": "não encontrado"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            dados = json.loads(self.rfile.read(min(n, 200_000)).decode("utf-8"))
        except Exception:
            return self._json(400, {"erro": "JSON inválido"})
        item = {k: str(dados.get(k, ""))[:20000] for k in CAMPOS}
        if not item["processo"] or not item["titulo"] or item["tipo"] not in ("tarefa", "prazo"):
            return self._json(400, {"erro": "processo, título e tipo (tarefa/prazo) são obrigatórios"})
        item.update(id=secrets.token_hex(6), status="pendente", criado_em=_agora(), erro="")
        with _trava:
            fila = _ler_fila()
            fila.append(item)
            _gravar_fila(fila[-500:])
        _evento.set()
        return self._json(200, {"ok": True, "id": item["id"]})

    def do_OPTIONS(self):  # sem CORS: navegadores bloqueiam chamadas de outros sites
        self.send_response(405)
        self.end_headers()

    def log_message(self, *args):
        pass


def main() -> None:
    cfg = djen_painel.carregar_config()
    porta = int(cfg.get("servidor_porta", 8765))
    # itens que ficaram "enviando" após queda voltam para a fila
    with _trava:
        fila = _ler_fila()
        for it in fila:
            if it["status"] == "enviando":
                it["status"] = "pendente"
        _gravar_fila(fila)
    threading.Thread(target=trabalhador, daemon=True).start()
    _evento.set()
    srv = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
    print(f"Painel em http://127.0.0.1:{porta}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
