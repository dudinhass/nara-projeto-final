"""Cliente HTTP reutilizável para a API OData v4 do IpeaData.

Comportamento da API verificado empiricamente (out/2026):

* ``Metadados`` aceita ``$filter`` com ``eq``/``startswith``, ``$top``,
  ``$skip`` e ``$orderby``; rejeita ``contains``, ``$select`` e ``$count``.
* ``Territorios`` aceita ``$filter`` com ``eq``/``startswith``.
* ``ValoresSerie(SERCODIGO='X')`` e ``Metadados('X')/Valores`` **ignoram**
  ``$filter``/``$top``/``$orderby`` em silêncio e devolvem a série inteira
  (ADMISNC: ~64 MB). Todo recorte territorial é feito no cliente.
* As respostas não são comprimidas e trazem ``Content-Length``, usado aqui
  para detectar downloads truncados.
* Nenhum endpoint testado devolveu ``@odata.nextLink``; a paginação é
  seguida mesmo assim, caso o servidor passe a usá-la.
"""

from __future__ import annotations

import email.utils
import gzip
import hashlib
import logging
import re
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urljoin, urlsplit

import requests

from coleta.armazenamento import substituir
from coleta.config import ConfigAPI, carregar_config_api

logger = logging.getLogger(__name__)

STATUS_RETENTAVEIS = frozenset({429, 500, 502, 503, 504})
_CODIGO_VALIDO = re.compile(r"^[A-Za-z0-9_ ]+$")
_T = TypeVar("_T")


class IpeaAPIError(Exception):
    """Erro base de comunicação com o IpeaData."""


class IpeaConnectionError(IpeaAPIError):
    """Falha de rede: DNS, conexão recusada, timeout, transferência interrompida."""


class IpeaHTTPError(IpeaAPIError):
    """Resposta HTTP com status de erro."""

    def __init__(self, status: int, url: str, mensagem: str = "") -> None:
        self.status = status
        self.url = url
        super().__init__(f"HTTP {status} em {url}" + (f": {mensagem}" if mensagem else ""))


class IpeaResponseError(IpeaAPIError):
    """Resposta recebida, mas com conteúdo fora do formato esperado."""


class ErroFonteNaoAutorizada(IpeaAPIError):
    """Tentativa de acessar um endereço que não pertence ao IpeaData (regra do projeto)."""


def verificar_url_autorizada(url: str, hosts: tuple[str, ...]) -> str:
    """Aceita só ``https`` e um dos hosts autorizados (sem credenciais embutidas na URL).

    Serve para a URL base, para qualquer link de paginação (``@odata.nextLink``) e para
    conferir o endereço final de cada resposta.
    """
    partes = urlsplit(url)
    if partes.scheme != "https" or partes.hostname not in hosts or partes.username or partes.password:
        raise ErroFonteNaoAutorizada(
            f"Endereço recusado: {url!r}. Só são aceitos endereços https dos hosts {list(hosts)} (IpeaData)."
        )
    return url


class _FalhaTransitoria(Exception):
    """Uso interno: falha que justifica nova tentativa."""

    def __init__(self, erro: IpeaAPIError, retry_after: float | None = None) -> None:
        super().__init__(str(erro))
        self.erro = erro
        self.retry_after = retry_after


@dataclass(frozen=True)
class RespostaAPI:
    """Uma página de resposta lida em memória (respostas pequenas)."""

    url: str
    status: int
    conteudo: bytes
    dados: dict[str, Any]
    coletado_em: str
    duracao_s: float

    @property
    def valores(self) -> list[dict[str, Any]]:
        return self.dados["value"]

    @property
    def proxima_pagina(self) -> str | None:
        return self.dados.get("@odata.nextLink")


@dataclass(frozen=True)
class Download:
    """Resposta gravada em disco (gzip) sem passar inteira pela memória."""

    url: str
    status: int
    arquivo: Path
    bytes: int
    content_length: int | None
    sha256: str
    coletado_em: str
    duracao_s: float


class LimitadorRequisicoes:
    """Garante um intervalo mínimo entre requisições, inclusive entre threads."""

    def __init__(
        self,
        intervalo_minimo: float,
        relogio: Callable[[], float] = time.monotonic,
        espera: Callable[[float], None] = time.sleep,
    ) -> None:
        self.intervalo_minimo = intervalo_minimo
        self._relogio = relogio
        self._espera = espera
        self._lock = threading.Lock()
        self._proxima_liberacao = 0.0

    def aguardar(self) -> None:
        with self._lock:
            agora = self._relogio()
            if agora < self._proxima_liberacao:
                self._espera(self._proxima_liberacao - agora)
                agora = self._relogio()
            self._proxima_liberacao = agora + self.intervalo_minimo


def interpretar_retry_after(valor: str | None, agora: datetime | None = None) -> float | None:
    """Converte ``Retry-After`` (segundos ou data HTTP) em segundos de espera."""
    if not valor:
        return None
    try:
        return max(0.0, float(valor))
    except ValueError:
        pass
    try:
        data = email.utils.parsedate_to_datetime(valor)
    except (TypeError, ValueError):
        return None
    referencia = agora or datetime.now(timezone.utc)
    return max(0.0, (data - referencia).total_seconds())


def _validar_codigo(codigo: str) -> str:
    """Impede que um código malformado altere a URL OData."""
    if not codigo or not _CODIGO_VALIDO.match(codigo):
        raise ValueError(f"Código inválido para a API: {codigo!r}")
    return codigo


def _extrair_mensagem_erro(resposta: requests.Response) -> str:
    try:
        corpo = resposta.json()
    except ValueError:
        return resposta.text[:200].strip()
    if isinstance(corpo, dict) and isinstance(corpo.get("error"), dict):
        return str(corpo["error"].get("message", ""))
    return ""


def _agora_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class IpeaClient:
    """Cliente com sessão persistente, timeout, novas tentativas e limite de taxa.

    Falhas de rede, downloads truncados e status 429/5xx são retentados com
    backoff exponencial (respeitando ``Retry-After``). Demais status de erro
    falham imediatamente. Pode ser usado como gerenciador de contexto.
    """

    def __init__(
        self,
        config: ConfigAPI | None = None,
        session: requests.Session | None = None,
        espera: Callable[[float], None] = time.sleep,
        limitador: LimitadorRequisicoes | None = None,
    ) -> None:
        self.config = config or carregar_config_api()
        self.base_url = verificar_url_autorizada(
            self.config.base_url.rstrip("/") + "/", self.config.hosts_autorizados
        )
        self.session = session or requests.Session()
        self.session.headers.update(
            {"Accept": "application/json", "User-Agent": self.config.user_agent}
        )
        self._espera = espera
        self.limitador = limitador or LimitadorRequisicoes(self.config.intervalo_minimo_segundos)
        self.requisicoes = 0

    def __enter__(self) -> IpeaClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.session.close()

    def _url(self, caminho: str) -> str:
        url = caminho if caminho.startswith("http") else urljoin(self.base_url, caminho)
        return verificar_url_autorizada(url, self.config.hosts_autorizados)

    @property
    def _timeout(self) -> tuple[float, float]:
        return (self.config.timeout_conexao, self.config.timeout_leitura)

    # --- Novas tentativas ------------------------------------------------------

    def _atraso(self, tentativa: int, retry_after: float | None) -> float:
        exponencial = self.config.backoff_segundos * 2 ** (tentativa - 1)
        return min(self.config.backoff_maximo_segundos, max(exponencial, retry_after or 0.0))

    def _com_tentativas(self, url: str, operacao: Callable[[], _T]) -> _T:
        total = self.config.max_tentativas_extras + 1
        ultimo_erro: IpeaAPIError | None = None
        for tentativa in range(1, total + 1):
            self.limitador.aguardar()
            self.requisicoes += 1
            try:
                return operacao()
            except _FalhaTransitoria as falha:
                ultimo_erro = falha.erro
                if tentativa == total:
                    break
                atraso = self._atraso(tentativa, falha.retry_after)
                logger.warning(
                    "Tentativa %d/%d falhou (%s). Nova tentativa em %.1fs.",
                    tentativa, total, falha.erro, atraso,
                    extra={"evento": "http_nova_tentativa", "url": url, "tentativa": tentativa},
                )
                self._espera(atraso)
        logger.error(
            "Todas as %d tentativas falharam para %s", total, url,
            extra={"evento": "http_falha_definitiva", "url": url},
        )
        assert ultimo_erro is not None
        raise ultimo_erro

    def _verificar_status(self, resposta: requests.Response) -> None:
        if 300 <= resposta.status_code < 400:
            # Redirecionamentos não são seguidos: poderiam levar a outro portal.
            raise ErroFonteNaoAutorizada(
                f"Redirecionamento recusado (HTTP {resposta.status_code}) em {resposta.url} "
                f"-> {resposta.headers.get('Location')!r}"
            )
        verificar_url_autorizada(resposta.url, self.config.hosts_autorizados)
        if resposta.status_code in STATUS_RETENTAVEIS:
            erro = IpeaHTTPError(resposta.status_code, resposta.url, _extrair_mensagem_erro(resposta))
            raise _FalhaTransitoria(erro, interpretar_retry_after(resposta.headers.get("Retry-After")))
        if not resposta.ok:
            raise IpeaHTTPError(resposta.status_code, resposta.url, _extrair_mensagem_erro(resposta))

    # --- Requisições em memória (respostas pequenas) ----------------------------

    def baixar(self, caminho: str, params: dict[str, str] | None = None) -> RespostaAPI:
        """GET de uma página pequena, validada como OData (objeto com ``value``)."""
        url = self._url(caminho)

        def operacao() -> RespostaAPI:
            inicio = time.monotonic()
            try:
                resposta = self.session.get(url, params=params, timeout=self._timeout, allow_redirects=False)
            except requests.RequestException as exc:
                raise _FalhaTransitoria(IpeaConnectionError(f"Falha de conexão com {url}: {exc}")) from exc
            self._verificar_status(resposta)
            dados = self._decodificar(resposta)
            duracao = round(time.monotonic() - inicio, 3)
            logger.info(
                "GET %s -> %d (%d registros, %.1fs)", resposta.url, resposta.status_code,
                len(dados["value"]), duracao,
                extra={"evento": "http_get", "url": resposta.url, "registros": len(dados["value"])},
            )
            return RespostaAPI(resposta.url, resposta.status_code, resposta.content, dados, _agora_utc(), duracao)

        return self._com_tentativas(url, operacao)

    def paginar(self, caminho: str, params: dict[str, str] | None = None) -> Iterator[RespostaAPI]:
        """Itera sobre as páginas seguindo ``@odata.nextLink`` quando existir."""
        visitadas: set[str] = set()
        pagina = self.baixar(caminho, params)
        while True:
            yield pagina
            proxima = pagina.proxima_pagina
            if not proxima:
                return
            if proxima in visitadas or len(visitadas) >= self.config.max_paginas:
                raise IpeaResponseError(f"Paginação interrompida: laço ou excesso de páginas em {proxima}")
            visitadas.add(proxima)
            pagina = self.baixar(proxima)

    def listar(self, caminho: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        registros: list[dict[str, Any]] = []
        for pagina in self.paginar(caminho, params):
            registros.extend(pagina.valores)
        return registros

    @staticmethod
    def _decodificar(resposta: requests.Response) -> dict[str, Any]:
        try:
            dados = resposta.json()
        except ValueError as exc:
            raise IpeaResponseError(f"Resposta não é JSON válido ({resposta.url})") from exc
        if not isinstance(dados, dict):
            raise IpeaResponseError(f"JSON inesperado: esperado objeto, recebido {type(dados).__name__}")
        if "error" in dados:
            mensagem = dados["error"].get("message") if isinstance(dados["error"], dict) else dados["error"]
            raise IpeaResponseError(f"API retornou erro: {mensagem}")
        if not isinstance(dados.get("value"), list):
            raise IpeaResponseError("JSON inesperado: campo 'value' ausente ou não é lista")
        return dados

    # --- Download em fluxo (respostas grandes) ----------------------------------

    def baixar_para_arquivo(
        self, caminho: str, destino: Path, params: dict[str, str] | None = None
    ) -> Download:
        """Grava a resposta em ``destino`` (gzip) bloco a bloco.

        O arquivo final só aparece depois que o corpo inteiro chegou e o
        tamanho confere com ``Content-Length``; até lá existe apenas
        ``destino.part``. O SHA-256 é calculado sobre o corpo original.
        A validação do JSON fica a cargo de ``coleta.leitor_odata``.
        """
        url = self._url(caminho)
        destino.parent.mkdir(parents=True, exist_ok=True)
        parcial = destino.with_name(destino.name + ".part")

        def operacao() -> Download:
            inicio = time.monotonic()
            hash_corpo = hashlib.sha256()
            total = 0
            try:
                with self.session.get(
                    url, params=params, timeout=self._timeout, stream=True, allow_redirects=False
                ) as resposta:
                    self._verificar_status(resposta)
                    cabecalho = resposta.headers.get("Content-Length")
                    comprimida = bool(resposta.headers.get("Content-Encoding"))
                    esperado = int(cabecalho) if cabecalho and not comprimida else None
                    with gzip.open(parcial, "wb") as saida:
                        for bloco in resposta.iter_content(chunk_size=1 << 20):
                            hash_corpo.update(bloco)
                            total += len(bloco)
                            saida.write(bloco)
                    url_final, status = resposta.url, resposta.status_code
            except requests.RequestException as exc:
                parcial.unlink(missing_ok=True)
                raise _FalhaTransitoria(IpeaConnectionError(f"Falha durante download de {url}: {exc}")) from exc
            except BaseException:
                parcial.unlink(missing_ok=True)
                raise
            if esperado is not None and total != esperado:
                parcial.unlink(missing_ok=True)
                raise _FalhaTransitoria(
                    IpeaResponseError(f"Download incompleto de {url}: {total} de {esperado} bytes")
                )
            substituir(parcial, destino)
            duracao = round(time.monotonic() - inicio, 3)
            logger.info(
                "Download %s -> %d (%.1f MB, %.1fs)", url_final, status, total / 1e6, duracao,
                extra={"evento": "http_download", "url": url_final, "bytes": total},
            )
            return Download(url_final, status, destino, total, esperado, hash_corpo.hexdigest(), _agora_utc(), duracao)

        return self._com_tentativas(url, operacao)

    # --- Endpoints de domínio ------------------------------------------------

    def testar_conexao(self) -> dict[str, Any]:
        """Consulta o documento de serviço OData (resposta leve) e mede a latência."""
        try:
            resposta = self.baixar("")
        except IpeaAPIError as exc:
            return {"ok": False, "url": self.base_url, "erro": str(exc)}
        return {
            "ok": True,
            "url": resposta.url,
            "status": resposta.status,
            "latencia_s": resposta.duracao_s,
            "entidades": [item.get("name") for item in resposta.valores],
        }

    def metadados(self, codigo: str) -> dict[str, Any] | None:
        """Metadados de uma série ou ``None`` se o código não existir."""
        registros = self.listar(f"Metadados('{_validar_codigo(codigo)}')")
        return registros[0] if registros else None

    def resposta_metadados(self, codigo: str) -> RespostaAPI:
        """Resposta completa (URL, horário, corpo) de ``Metadados('X')``, para servir de evidência."""
        return self.baixar(f"Metadados('{_validar_codigo(codigo)}')")

    def resposta_territorios(self, codigo_uf: str) -> RespostaAPI:
        """Resposta completa do cadastro de municípios de uma UF no IpeaData."""
        return self.baixar("Territorios", self.filtro_municipios_uf(codigo_uf))

    def resposta_estado(self, codigo_uf: str) -> RespostaAPI:
        """Resposta de ``Territorios`` para o nível Estados (confere o código da UF no IpeaData)."""
        if not codigo_uf.isdigit():
            raise ValueError(f"Código de UF inválido: {codigo_uf!r}")
        return self.baixar("Territorios", {"$filter": f"NIVNOME eq 'Estados' and TERCODIGO eq '{codigo_uf}'"})

    def catalogo_metadados(self) -> list[dict[str, Any]]:
        """Metadados de todas as séries (~4 mil registros, ~8 MB)."""
        return self.listar("Metadados")

    def caminho_valores(self, codigo: str) -> str:
        return f"ValoresSerie(SERCODIGO='{_validar_codigo(codigo)}')"

    def valores_serie(self, codigo: str) -> list[dict[str, Any]]:
        """Valores em memória. Para séries grandes prefira ``baixar_para_arquivo``."""
        return self.listar(self.caminho_valores(codigo))

    @staticmethod
    def filtro_municipios_uf(codigo_uf: str) -> dict[str, str]:
        if not codigo_uf.isdigit():
            raise ValueError(f"Código de UF inválido: {codigo_uf!r}")
        return {"$filter": f"NIVNOME eq 'Municípios' and startswith(TERCODIGO,'{codigo_uf}')"}

    def territorios(self, filtro: str | None = None) -> list[dict[str, Any]]:
        params = {"$filter": filtro} if filtro else None
        return self.listar("Territorios", params)

    def municipios_uf(self, codigo_uf: str) -> list[dict[str, Any]]:
        """Municípios de uma UF segundo o cadastro de territórios do IpeaData."""
        return self.listar("Territorios", self.filtro_municipios_uf(codigo_uf))
