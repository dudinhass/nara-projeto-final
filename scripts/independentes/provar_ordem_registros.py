"""Prova se a diferença de SHA-256 entre o bruto guardado e a resposta atual é só de ORDEM dos registros.

Resumo independente da ordem: soma (mod 2^256) dos SHA-256 de cada registro serializado de forma canônica.
Dois arquivos com o mesmo conjunto de registros, em qualquer ordem, dão o mesmo resumo.
"""
import gzip
import hashlib
import json
import sys

import ijson
import requests

URL = "https://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='{}')"
MOD = 1 << 256


def resumo(fluxo):
    total, n, primeiro = 0, 0, None
    for rec in ijson.items(fluxo, "value.item", use_float=True):
        canon = json.dumps(rec, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        total = (total + int.from_bytes(hashlib.sha256(canon.encode("utf-8")).digest(), "big")) % MOD
        n += 1
        primeiro = primeiro or (rec["NIVNOME"], rec["TERCODIGO"], rec["VALDATA"][:10])
    return n, f"{total:064x}"[:16], primeiro


for codigo, arquivo in zip(sys.argv[1::2], sys.argv[2::2]):
    with gzip.open(arquivo, "rb") as f:
        guardado = resumo(f)
    for tentativa in range(1, 4):
        try:
            with requests.get(URL.format(codigo), stream=True, timeout=(10, 300), allow_redirects=False) as r:
                r.raise_for_status()
                agora = resumo(r.raw)
            break
        except requests.RequestException as exc:
            print(f"  tentativa {tentativa} falhou: {type(exc).__name__}", flush=True)
    else:
        print(f"{codigo}: NÃO CONCLUÍDA")
        continue
    print(f"{codigo}: guardado: {guardado[0]} registros, resumo {guardado[1]}, 1º registro {guardado[2]}")
    print(f"{codigo}: agora:    {agora[0]} registros, resumo {agora[1]}, 1º registro {agora[2]}")
    print(f"{codigo}: MESMO CONJUNTO DE REGISTROS: {guardado[:2] == agora[:2]} | MESMA ORDEM: {guardado[2] == agora[2]}", flush=True)
