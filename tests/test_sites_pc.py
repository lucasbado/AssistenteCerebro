from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento
from servicos.roteamento_pedidos import interpretar_abertura, resolver_abertura
from servicos.sites_pc import resolver_site_pc, url_explicita


@pytest.mark.parametrize("name,url", [
    ("HBO Max", "https://www.hbomax.com/"), ("Max", "https://www.hbomax.com/"),
    ("max.exe", "https://www.hbomax.com/"), ("com.wbd.stream", "https://www.hbomax.com/"),
    ("hbomax.com", "https://www.hbomax.com/"), ("Netflix", "https://www.netflix.com/"),
    ("Prime Video", "https://www.primevideo.com/"), ("Prime", "https://www.primevideo.com/"),
    ("Amazon Prime", "https://www.primevideo.com/"), ("Disney Plus", "https://www.disneyplus.com/"),
    ("github.com", "https://github.com"),
    ("https://example.com/Video/ABC?share=XYZ#Frame", "https://example.com/Video/ABC?share=XYZ#Frame"),
])
def test_servicos_e_dominios_resolvem_sem_tentar_executavel(name, url):
    assert resolver_site_pc(name) == url


@pytest.mark.parametrize("value", ["code.exe", "Spotify", "arquivo.py", "com.google.android.youtube", "com.spotify.music", "javascript:alert(1)", "file:///C:/Windows/a.exe", "dois nomes", "https://user:password@example.com"])
def test_nome_de_app_e_protocolo_local_nao_viram_site(value):
    assert url_explicita(value) is None


@pytest.mark.parametrize("text,value", [
    ("abre HBO Max no PC", "https://www.hbomax.com/"),
    ("Ollie, pode abrir o site da HBO Max no PC?", "https://www.hbomax.com/"),
    ("abra o site github.com", "https://github.com"),
    ("abre https://example.com/Video/ABC?share=XYZ no PC", "https://example.com/Video/ABC?share=XYZ"),
])
def test_pedido_concreto_vai_ao_site_e_preserva_endereco(text, value):
    parsed = interpretar_abertura(text)
    assert parsed
    action = parsed["execucao_direta"][0]
    event = EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO,
        origem=OrigemEvento.USUARIO, pacote="pc.chat", payload={"texto": text})
    assert resolver_abertura(event, action["comando"], action["parametro"]) == ("PC", "abrir_url", value)


def test_ponte_local_corrige_comando_hbo_mesmo_antes_do_deploy():
    from scripts.pc_command import executar
    service = SimpleNamespace(abrir_url=Mock(), abrir_app=Mock())
    assert executar("abrir_app", "HBO Max", service=service) == {"status": "ok"}
    service.abrir_url.assert_called_once_with("https://www.hbomax.com/")
    service.abrir_app.assert_not_called()


def test_app_instalado_continua_usando_executor_de_apps():
    from scripts.pc_command import executar
    service = SimpleNamespace(abrir_url=Mock(), abrir_app=Mock(return_value=True))
    executar("abrir_app", "Spotify", service=service)
    service.abrir_app.assert_called_once_with("Spotify")
    service.abrir_url.assert_not_called()


def test_ponte_resolve_servico_inclusive_quando_llm_diz_url_sem_endereco():
    from scripts.pc_command import executar
    service = SimpleNamespace(abrir_url=Mock())
    executar("abrir_url", "HBO Max", service=service)
    service.abrir_url.assert_called_once_with("https://www.hbomax.com/")
