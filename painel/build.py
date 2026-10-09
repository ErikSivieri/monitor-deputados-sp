"""Gera o HTML do painel com os dados embutidos: python painel/build.py [saida.html]"""
import json
import sys
from pathlib import Path

raiz = Path(__file__).resolve().parent.parent
dados = json.loads((raiz / "data" / "painel.json").read_text(encoding="utf-8"))
txt = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
html = (raiz / "painel" / "template.html").read_text(encoding="utf-8").replace("/*__DADOS__*/", txt)
saida = Path(sys.argv[1]) if len(sys.argv) > 1 else raiz / "painel" / "monitor-deputados-sp.html"
saida.write_text(html, encoding="utf-8")
print(f"{saida} ({saida.stat().st_size/1e6:.2f} MB)")
