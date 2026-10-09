"""Executa a coleta completa: python -m coletor"""
import json
import datetime as dt

from . import alesp, camara, montar, tse
from .util import DADOS, FORCAR, STATUS, log, registrar


def main():
    log("início; atualização completa:", FORCAR)
    cand = tse.candidaturas()

    cad = camara.deputados()
    fed = None
    if cad:
        ids = [d["id"] for d in cad["deputados"]]
        desp = camara.despesas(ids)
        props = camara.proposicoes(ids)
        vots = camara.votacoes(ids)
        fed = montar.federal(cad, desp, props, vots, cand)

    ecad = alesp.cadastro()
    edesp = alesp.despesas()
    eprops = alesp.proposituras()
    epres = alesp.presencas()
    est = montar.estadual(ecad, edesp, eprops, epres, cand)

    agora = dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))).strftime("%Y-%m-%d %H:%M")
    resumo = {k: {"ok": v.get("ok", True), "erro": v.get("erro")} for k, v in STATUS.items()}
    painel = {"meta": {"geradoEm": agora, "inicio": 2015, "fontes": resumo,
                       "sucessoras": montar.SUCESSORAS},
              "federal": fed, "estadual": est}
    antigo = DADOS / "painel.json"
    if fed is None and antigo.exists():
        # Câmara fora do ar: mantém a parte federal do último arquivo bom
        painel["federal"] = json.loads(antigo.read_text(encoding="utf-8")).get("federal")
        painel["meta"]["avisos"] = ["Dados federais não atualizados hoje (falha na fonte)."]
    antigo.write_text(json.dumps(painel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    registrar("geral", geradoEm=agora, tamanho_painel_mb=round(antigo.stat().st_size / 1e6, 2))
    (DADOS / "status.json").write_text(json.dumps(STATUS, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    log("fim")


if __name__ == "__main__":
    main()
