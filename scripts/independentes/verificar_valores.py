"""Verificação independente: nenhum módulo do projeto é usado para ler o IpeaData ou normalizar os dados.

Baixa ValoresSerie direto (requests + ijson), monta (nível, território, mês) -> valor e compara com o banco
lido por SQL puro (psycopg). Tenta cada série até 4 vezes (o servidor às vezes demora mais que o timeout).
"""
import hashlib
import sys
import time

import ijson
import psycopg
import requests

URL = "https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='{}')"
NIVEL = {"Municípios": "municipio", "Estados": "estado", "Brasil": "brasil", "": "brasil"}

senha = [l.split("=", 1)[1].strip() for l in open(".env", encoding="utf-8") if l.startswith("POSTGRES_PASSWORD=")][0]
con = psycopg.connect(host="localhost", port=5432, user="emprego", password=senha, dbname="emprego_maranhao")


class Tee:
    def __init__(self, fonte, h):
        self.fonte, self.h = fonte, h

    def read(self, n=-1):
        b = self.fonte.read(n)
        self.h.update(b)
        return b


def baixar(codigo):
    h = hashlib.sha256()
    vivo, registros = {}, 0
    with requests.get(URL.format(codigo), stream=True, timeout=(10, 300), allow_redirects=False) as r:
        r.raise_for_status()
        assert r.url.startswith("https://www.ipeadata.gov.br/"), r.url
        for rec in ijson.items(Tee(r.raw, h), "value.item", use_float=True):
            registros += 1
            assert rec["SERCODIGO"] == codigo
            nivel = NIVEL.get((rec.get("NIVNOME") or "").strip())
            ter = str(rec.get("TERCODIGO") or "").strip()
            if nivel is None or (nivel == "municipio" and not ter.startswith("21")) or (nivel == "estado" and ter != "21"):
                continue
            vivo[(nivel, "BR" if nivel == "brasil" else ter, rec["VALDATA"][:10])] = rec["VALVALOR"]
    return vivo, registros, h.hexdigest()


tot = dict(ok=0, dif=0, so_banco=0, so_fonte=0)
concluidas, falhas = [], []
for codigo in sys.argv[1:]:
    for tentativa in range(1, 5):
        try:
            vivo, registros, sha = baixar(codigo)
            break
        except (requests.RequestException, OSError) as exc:
            print(f"  {codigo}: tentativa {tentativa} falhou ({type(exc).__name__}); aguardando", flush=True)
            time.sleep(5 * tentativa)
    else:
        falhas.append(codigo)
        print(f"{codigo}: NÃO CONCLUÍDA após 4 tentativas", flush=True)
        continue
    with con.cursor() as cur:
        cur.execute("SELECT r.nivel_territorial, r.cod_territorio, to_char(r.data_referencia,'YYYY-MM-DD'), r.valor "
                    "FROM registros_emprego r JOIN series_indicadores s ON s.id = r.serie_id WHERE s.codigo = %s", (codigo,))
        banco = {(n, c, d): v for n, c, d, v in cur.fetchall()}
    iguais = sum(1 for k, v in banco.items() if k in vivo and float(vivo[k]) == float(v))
    dif = [k for k, v in banco.items() if k in vivo and float(vivo[k]) != float(v)]
    so_banco = [k for k in banco if k not in vivo]
    so_fonte = [k for k in vivo if k not in banco]
    tot["ok"] += iguais; tot["dif"] += len(dif); tot["so_banco"] += len(so_banco); tot["so_fonte"] += len(so_fonte)
    concluidas.append(codigo)
    print(f"{codigo}: resposta={registros} registros, sha256={sha[:16]}…, no escopo={len(vivo)}, banco={len(banco)}, "
          f"iguais={iguais}, diferentes={len(dif)}, só no banco={len(so_banco)}, só na fonte={len(so_fonte)}", flush=True)
print(f"CONCLUÍDAS {len(concluidas)}/{len(sys.argv) - 1}; NÃO CONCLUÍDAS: {falhas or 'nenhuma'}")
print(f"TOTAL iguais={tot['ok']} diferentes={tot['dif']} só_no_banco={tot['so_banco']} só_na_fonte={tot['so_fonte']}")
