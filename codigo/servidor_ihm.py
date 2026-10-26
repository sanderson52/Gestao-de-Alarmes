"""
IHM de demonstração (protótipo acadêmico) LIGADA ao motor real de automacao.py.

Executar:   python servidor_ihm.py
Abrir:      http://localhost:8000   (o navegador abre automaticamente)

- Só biblioteca padrão do Python (http.server + json).
- O navegador apenas EXIBE o estado; toda decisão (filtrar, priorizar, correlacionar,
  reconhecer) é feita pelo AlarmProcessor no Python.
- Os sinais vêm do cenário SIMULADO de cenario_compressor.py (não há planta real).
"""
import json
import logging
import os
import sys
import threading
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

import cenario_compressor as cen

logging.getLogger("IndustrialAlarmEngine").setLevel(logging.WARNING)

PASTA = os.path.dirname(os.path.abspath(__file__))
PORTA = int(os.environ.get("PORTA_IHM", "8000"))


def relogio(ts: float) -> str:
    """Relógio fictício da simulação: início às 14:00:00."""
    s = int(round(ts - cen.T_INICIO)) + 14 * 3600
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


class Simulacao:
    def __init__(self):
        self.lock = threading.Lock()
        self.reiniciar()

    def reiniciar(self):
        self.passos = cen.gerar_amostras()
        self.idx = 0
        self.a = cen.AnunciadorSemRacionalizacao(cen.TAGS)
        self.b = cen.novo_motor()
        self.ultimos = {}

    def avancar(self, n: int = 1, ate_s: float = None):
        if ate_s is not None:
            n = max(0, int(ate_s / cen.DT) - self.idx + 1)
        for _ in range(n):
            if self.idx >= len(self.passos):
                break
            for sig in self.passos[self.idx]:
                self.a.processar(sig)
                self.b.process_telemetry(sig)
                self.ultimos[sig.sensor_id] = sig
            self.idx += 1

    def estado(self):
        t_rel = max(0.0, (self.idx - 1) * cen.DT)
        narr = ""
        for s, texto in cen.EVENTOS_ROTEIRO:
            if t_rel >= s:
                narr = texto
        cfg = {t["sensor_id"]: t for t in cen.TAGS}
        processo = []
        for t in cen.TAGS:
            sig = self.ultimos.get(t["sensor_id"])
            al = self.b.active_alarms.get(t["tag"])
            qal = self.b.active_alarms.get(t["tag"] + "__QUALIDADE")
            processo.append({
                "sensor_id": t["sensor_id"], "equip": t["equipment"], "unidade": t["unit"],
                "limite": t["limit"], "dir": t["direction"],
                "valor": None if sig is None else sig.value,
                "qualidade_ok": True if sig is None else sig.quality_good,
                "prioridade_alarme": al.priority.name if al else (qal.priority.name if qal else None),
            })
        ativos = []
        for al in self.b.get_sorted_active():
            d = al.to_dict()
            d["hora"] = relogio(al.timestamp)
            ativos.append(d)
        notif = [{"hora": relogio(n["timestamp"]), "texto": n["texto"]} for n in self.a.notificacoes]
        return {
            "passo": self.idx, "total": len(self.passos), "t_rel": t_rel,
            "relogio": relogio(cen.T_INICIO + t_rel), "narracao": narr,
            "processo": processo,
            "A": {"total": len(notif), "notificacoes": notif[-80:]},
            "B": {
                "ativos": ativos,
                "contadores": self.b.counters,
                "operador_log": [dict(e, hora=relogio(e["timestamp"])) for e in self.b.operator_log[-8:]],
                "eventos": [dict(e, hora=relogio(e["timestamp"])) for e in self.b.event_log[-10:]],
                "suprimidos": [dict(e, hora=relogio(e["timestamp"])) for e in self.b.suppressed_log[-10:]],
            },
        }


SIM = Simulacao()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except ValueError:
            return {}

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(PASTA, "ihm", "index.html"), "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path.startswith("/api/estado"):
            with SIM.lock:
                self._json(SIM.estado())
        else:
            self._json({"erro": "não encontrado"}, 404)

    def do_POST(self):
        body = self._body()
        with SIM.lock:
            if self.path == "/api/avancar":
                SIM.avancar(int(body.get("n", 1)), body.get("ate_s"))
            elif self.path == "/api/reconhecer":
                ok = SIM.b.acknowledge(str(body.get("tag", "")), str(body.get("operador", "Operador")) or "Operador",
                                       note=str(body.get("observacao", "")))
                if not ok:
                    return self._json({"erro": "alarme não está aguardando reconhecimento"}, 409)
            elif self.path == "/api/reiniciar":
                SIM.reiniciar()
            else:
                return self._json({"erro": "não encontrado"}, 404)
            self._json(SIM.estado())


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORTA), Handler)
    url = f"http://localhost:{PORTA}"
    print(f"IHM de demonstração em {url}  (Ctrl+C para encerrar)")
    if "--sem-navegador" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")


if __name__ == "__main__":
    main()
