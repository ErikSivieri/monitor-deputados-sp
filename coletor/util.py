"""Funções comuns: download com repetição, cache por ano, normalização de nomes e registro de status."""
import datetime as dt
import json
import os
import re
import time
import traceback
import unicodedata
import zipfile
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "data"
CACHE = DADOS / "cache"
BRUTO = RAIZ / ".bruto"
INICIO = 2015

for p in (DADOS, CACHE, BRUTO):
    p.mkdir(parents=True, exist_ok=True)

HOJE = dt.date.today()
ANO_ATUAL = HOJE.year
# Atualização completa (inclusive anos já fechados) aos domingos, no dia 1º ou quando pedido.
FORCAR = os.environ.get("FORCAR") == "1" or HOJE.weekday() == 6 or HOJE.day == 1

SESSAO = requests.Session()
SESSAO.headers["User-Agent"] = "monitor-deputados-sp (projeto pessoal de estudo; github.com/ErikSivieri/monitor-deputados-sp)"

STATUS = {}


def registrar(fonte, **kw):
    STATUS.setdefault(fonte, {}).update(kw)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def protegido(fonte):
    """Decorador: um erro numa fonte fica registrado no status e não derruba as demais."""
    def dec(func):
        def inner(*a, **kw):
            t0 = time.time()
            try:
                r = func(*a, **kw)
                registrar(fonte, ok=True, segundos=round(time.time() - t0))
                return r
            except Exception as e:  # noqa: BLE001
                log("ERRO em", fonte, e)
                registrar(fonte, ok=False, erro=f"{type(e).__name__}: {e}",
                          trace=traceback.format_exc()[-3000:], segundos=round(time.time() - t0))
                return None
        return inner
    return dec


def baixar(url, nome=None, tentativas=4, timeout=600):
    """Baixa para .bruto/ e devolve o caminho. Devolve None se o arquivo não existir (404)."""
    nome = nome or re.sub(r"[^A-Za-z0-9._-]", "_", url.split("//", 1)[-1])
    destino = BRUTO / nome
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    for i in range(tentativas):
        try:
            with SESSAO.get(url, stream=True, timeout=timeout) as r:
                if r.status_code == 404:
                    log("404", url)
                    return None
                r.raise_for_status()
                tmp = destino.with_suffix(destino.suffix + ".tmp")
                with open(tmp, "wb") as f:
                    for bloco in r.iter_content(1 << 20):
                        f.write(bloco)
                tmp.rename(destino)
                log("baixado", url, f"{destino.stat().st_size/1e6:.1f} MB")
                return destino
        except Exception as e:  # noqa: BLE001
            log("falha", url, e, "tentativa", i + 1)
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"não foi possível baixar {url}")


def get_json(url, params=None, tentativas=5):
    ultimo = ""
    for i in range(tentativas):
        try:
            r = SESSAO.get(url, params=params, timeout=90, headers={"Accept": "application/json"})
            if r.status_code == 429:
                time.sleep(10 * (i + 1))
                continue
            if r.status_code >= 400:
                ultimo = f"HTTP {r.status_code}: {r.text[:300]}"
                if 400 <= r.status_code < 500 and r.status_code != 408:
                    break
                raise RuntimeError(ultimo)
            time.sleep(0.2)  # pausa entre requisições, como pede a equipe de Dados Abertos
            return r.json()
        except Exception as e:  # noqa: BLE001
            ultimo = ultimo or str(e)
            log("falha", url, e, "tentativa", i + 1)
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"falha em {url} ({ultimo})")


def paginar(url, params=None):
    """Percorre todas as páginas de um endpoint da API da Câmara."""
    dados, prox, p = [], url, params
    while prox:
        j = get_json(prox, p)
        dados.extend(j.get("dados", []))
        prox = next((l["href"] for l in j.get("links", []) if l.get("rel") == "next"), None)
        p = None
    return dados


def abrir_zip(caminho, termina_com=None):
    z = zipfile.ZipFile(caminho)
    nomes = [n for n in z.namelist() if not n.endswith("/")]
    if termina_com:
        cand = [n for n in nomes if n.lower().endswith(termina_com.lower())]
        nomes = cand or nomes
    return z.open(nomes[0]), nomes


def norm(txt):
    if txt is None:
        return ""
    txt = unicodedata.normalize("NFKD", str(txt)).encode("ascii", "ignore").decode()
    txt = re.sub(r"[^A-Za-z0-9 ]", " ", txt.upper())
    return re.sub(r"\s+", " ", txt).strip()


def num(txt):
    """Converte '1.234,56' ou '1234.56' em float."""
    if txt is None:
        return 0.0
    s = str(txt).strip()
    if not s:
        return 0.0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def com_cache(nome, ano, func):
    """Anos já fechados (antes do ano anterior) ficam em cache; o ano corrente e o anterior são sempre recalculados."""
    arq = CACHE / f"{nome}-{ano}.json"
    if arq.exists() and ano < ANO_ATUAL - 1 and not FORCAR:
        return json.loads(arq.read_text(encoding="utf-8"))
    r = func(ano)
    if r is not None:
        arq.write_text(json.dumps(r, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    elif arq.exists():  # fonte fora do ar: usa o último cache bom
        log("usando cache antigo de", nome, ano)
        return json.loads(arq.read_text(encoding="utf-8"))
    return r


def col(df, *opcoes):
    """Acha a coluna do DataFrame entre nomes possíveis (sem diferenciar maiúsculas)."""
    mapa = {c.lower(): c for c in df.columns}
    for o in opcoes:
        if o.lower() in mapa:
            return mapa[o.lower()]
    raise KeyError(f"nenhuma das colunas {opcoes} em {list(df.columns)[:40]}")


def iso(data):
    """Normaliza datas 'AAAA-MM-DD...' ou 'DD/MM/AAAA...' para 'AAAA-MM-DD'."""
    s = (data or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return ""
