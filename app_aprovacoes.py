"""
Aprovações Coupa — interface gráfica.

Usa o main.py como "motor": a tela guarda o limite e os filtros, cuida do
login no Coupa e mostra o andamento das aprovações.
"""
import re
import ctypes
import json
import os
import queue
import sys
import threading
import time
import traceback
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

PASTA_APP = Path(__file__).resolve().parent
ARQUIVO_CONFIG = PASTA_APP.parent / "config.json"   # fora de /app: sobrevive às atualizações
ICONE = PASTA_APP / "icone.ico"
sys.path.insert(0, str(PASTA_APP))

# Antes de carregar o motor: se houver versão nova na pasta da rede, atualiza e reabre.
try:
    import atualizador   # noqa: E402
    atualizador.verificar(__file__)
    VERSAO = atualizador.versao_instalada(__file__)
except Exception:
    VERSAO = ""

import main as motor   # noqa: E402


# =====================================================================
#                         CORES E FONTES
# =====================================================================
FUNDO = "#F4F6FA"
CARTAO = "#FFFFFF"
BORDA = "#E3E8EF"
TEXTO = "#1F2937"
SUAVE = "#6B7280"
CINZA_CLARO = "#EEF1F5"
HOVER_NEUTRO = "#E9EDF3"
AZUL = "#2F6FEB"
AZUL_ESCURO = "#2259C7"
AZUL_CLARO = "#EAF1FE"
AZUL_HOVER = "#D9E6FD"
AZUL_DESATIVADO = "#9DB7EE"
VERDE = "#1E9E5A"
VERDE_ESCURO = "#17824A"
VERDE_CLARO = "#E7F6EE"
AMARELO = "#B7791F"
AMARELO_CLARO = "#FDF4E3"
VERMELHO = "#D64545"
VERMELHO_CLARO = "#FDECEC"
CINZA_TEXTO = "#5B6472"
ROXO = "#6B4EE6"
FAMILIA = "Segoe UI"


def fonte(tamanho=13, peso="normal"):
    return ctk.CTkFont(family=FAMILIA, size=tamanho, weight=peso)


def botao_primario(pai, texto, comando, **kw):
    kw.setdefault("height", 38)
    return ctk.CTkButton(pai, text=texto, command=comando, corner_radius=8, fg_color=AZUL,
                         hover_color=AZUL_ESCURO, font=fonte(13, "bold"), **kw)


def botao_secundario(pai, texto, comando, **kw):
    kw.setdefault("height", 38)
    return ctk.CTkButton(pai, text=texto, command=comando, corner_radius=8, fg_color=AZUL_CLARO,
                         hover_color=AZUL_HOVER, text_color=AZUL, font=fonte(13, "bold"), **kw)


def botao_texto(pai, texto, comando, cor=SUAVE, **kw):
    kw.setdefault("height", 30)
    return ctk.CTkButton(pai, text=texto, command=comando, fg_color="transparent",
                         hover_color=HOVER_NEUTRO, text_color=cor, font=fonte(12), **kw)


def aplicar_icone(janela):
    if sys.platform == "win32" and ICONE.exists():
        try:
            janela.iconbitmap(str(ICONE))
        except Exception:
            pass


def abrir_no_windows(caminho):
    if hasattr(os, "startfile"):
        os.startfile(str(caminho))


def formatar_tempo(segundos):
    segundos = int(segundos)
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h}h{m:02d}" if h else f"{m:02d}:{s:02d}"


def carregar_config():
    try:
        return json.loads(ARQUIVO_CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def salvar_config(dados):
    try:
        ARQUIVO_CONFIG.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# =====================================================================
#      PONTE ENTRE O MOTOR (thread de trabalho) E A TELA
# =====================================================================
fila_ui = queue.Queue()


class EscritorFila:
    """Tudo que o motor imprime vai para os detalhes técnicos."""
    def write(self, texto):
        if texto:
            fila_ui.put(("log", texto))

    def flush(self):
        pass


sys.stdout = EscritorFila()
sys.stderr = EscritorFila()


def notificar_tela(evento, **dados):
    fila_ui.put(("evento", (evento, dados)))


def esperar_resposta_da_tela(tipo, **dados):
    """Chamado pela thread do motor: pede algo à tela e espera a resposta."""
    pedido = {"tipo": tipo, "dados": dados, "evento": threading.Event(), "resposta": None}
    fila_ui.put(("pedido", pedido))
    pedido["evento"].wait()
    return pedido["resposta"]


# =====================================================================
#                         COMPONENTES
# =====================================================================
class Cartao(ctk.CTkFrame):
    def __init__(self, pai, **kw):
        super().__init__(pai, fg_color=CARTAO, corner_radius=14, border_width=1,
                         border_color=BORDA, **kw)


class Contador(ctk.CTkFrame):
    """Quadradinho com número grande e legenda; o número 'rola' até o valor novo."""
    def __init__(self, pai, legenda, cor, fundo):
        super().__init__(pai, fg_color=fundo, corner_radius=10)
        self.mostrado = 0
        self.alvo = 0
        self.lbl = ctk.CTkLabel(self, text="0", font=fonte(24, "bold"), text_color=cor)
        self.lbl.pack(pady=(10, 0))
        self.lbl_legenda = ctk.CTkLabel(self, text=legenda, font=fonte(12), text_color=cor)
        self.lbl_legenda.pack(pady=(0, 10))

    def definir(self, valor, animar=True):
        self.alvo = max(0, valor)
        if not animar:
            self.mostrado = self.alvo
            self.lbl.configure(text=str(self.alvo))

    def passo(self):
        if self.mostrado != self.alvo:
            dif = self.alvo - self.mostrado
            salto = max(1, abs(dif) // 6)
            self.mostrado += salto if dif > 0 else -salto
            self.lbl.configure(text=str(self.mostrado))


# =====================================================================
#                              A TELA
# =====================================================================
LIMITE_PADRAO = 10000.0


class App(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=FUNDO)
        ctk.set_appearance_mode("light")
        self.title("Aprovações Coupa" + (f"  ·  versão {VERSAO}" if VERSAO else ""))
        aplicar_icone(self)
        self.minsize(700, 640)
        self._centralizar(780, 860)

        cfg = carregar_config()
        self.url = cfg.get("url", "") or motor.COUPA_URL
        self.limite = float(cfg.get("limite", LIMITE_PADRAO))
        self.filtros = cfg.get("filtros") or [dict(f) for f in motor.FILTROS_PADRAO]
        if motor.validar_filtros(self.filtros):
            self.filtros = [dict(f) for f in motor.FILTROS_PADRAO]
        self.ja_logou = cfg.get("ja_logou", False)
        self.boas_vindas = cfg.get("boas_vindas", False)
        self.auto_ativo = cfg.get("auto_ativo", False)
        self.auto_minutos = int(cfg.get("auto_minutos", 60))
        self.auto_horario_comercial = cfg.get("auto_horario_comercial", False)
        self.auto_esconder = cfg.get("auto_esconder", False)
        self.proxima_auto = None          # quando é a próxima execução automática (time.time())
        self.execucao_automatica = False  # a execução atual foi disparada pelo relógio?
        self.historico_auto = []          # resumos das últimas execuções automáticas

        self.thread = None
        self.parar = threading.Event()
        self.inicio_execucao = None
        self.alvo_barra = 0.0
        self.contagem = {}
        self.total_valor = 0.0
        self.ultimo_resultado = None

        self.corpo = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                            scrollbar_button_color="#DCE1E8",
                                            scrollbar_button_hover_color="#B8C0CC")
        self.corpo.pack(fill="both", expand=True, padx=14, pady=10)
        self.miolo = ctk.CTkFrame(self.corpo, fg_color="transparent")
        self.miolo.pack(fill="both", expand=True, padx=14, pady=8)

        self._montar_cabecalho()
        self._montar_regra()
        self._montar_botao_principal()
        self._montar_automatico()
        self._montar_andamento()
        self._montar_detalhes()
        self._atualizar_textos()

        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        self.after(60, self._processar_fila)
        self.after(16, self._animar)
        self.after(1000, self._relogio)
        self.after(5000, self._vigiar_automatico)
        if self.auto_ativo:
            self.sw_auto.select()
            self._agendar_proxima(primeira=True)
        if not self.boas_vindas:
            self.after(500, self._primeira_vez)

    def _centralizar(self, largura, altura):
        self.update_idletasks()
        altura = min(altura, self.winfo_screenheight() - 80)
        x = max(0, (self.winfo_screenwidth() - largura) // 2)
        y = max(0, (self.winfo_screenheight() - altura) // 2 - 20)
        self.geometry(f"{largura}x{altura}+{x}+{y}")

    # ---------- montagem ----------
    def _montar_cabecalho(self):
        topo = ctk.CTkFrame(self.miolo, fg_color="transparent")
        topo.pack(fill="x", pady=(0, 18))
        ctk.CTkLabel(topo, text="R$", font=fonte(18, "bold"), width=52, height=52, corner_radius=14,
                     fg_color=ROXO, text_color="#FFFFFF").pack(side="left", padx=(0, 14))
        textos = ctk.CTkFrame(topo, fg_color="transparent")
        textos.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(textos, text="Aprovações Coupa", font=fonte(22, "bold"),
                     text_color=TEXTO, anchor="w").pack(anchor="w")
        ctk.CTkLabel(textos, text="Aprova as requisições abaixo do limite. O resto fica para você.",
                     font=fonte(13), text_color=SUAVE, anchor="w").pack(anchor="w")
        lado = ctk.CTkFrame(topo, fg_color="transparent")
        lado.pack(side="right")
        self.btn_login = botao_texto(lado, "🔑  Entrar no Coupa", self._fazer_login, width=140)
        self.btn_login.pack(anchor="e")
        self.btn_config = botao_texto(lado, "⚙  Configurações", self._abrir_configuracoes, width=140)
        self.btn_config.pack(anchor="e")

    def _montar_regra(self):
        card = Cartao(self.miolo)
        card.pack(fill="x", pady=(0, 18))
        ctk.CTkLabel(card, text="Aprovar automaticamente abaixo de", font=fonte(14, "bold"),
                     text_color=TEXTO, anchor="w").pack(anchor="w", padx=18, pady=(14, 6))

        linha = ctk.CTkFrame(card, fg_color="transparent")
        linha.pack(fill="x", padx=18)
        ctk.CTkLabel(linha, text="R$", font=fonte(22, "bold"), text_color=SUAVE).pack(side="left", padx=(0, 8))
        self.ent_limite = ctk.CTkEntry(linha, width=200, height=44, corner_radius=10, font=fonte(22, "bold"),
                                       border_color=BORDA, justify="left")
        self.ent_limite.insert(0, motor.formatar_brl(self.limite))
        self.ent_limite.pack(side="left")
        self.ent_limite.bind("<FocusOut>", lambda _: self._ler_limite())
        self.ent_limite.bind("<Return>", lambda _: (self._ler_limite(), self.focus()))
        self.lbl_limite_erro = ctk.CTkLabel(linha, text="", font=fonte(12), text_color=VERMELHO)
        self.lbl_limite_erro.pack(side="left", padx=12)

        cab_filtros = ctk.CTkFrame(card, fg_color="transparent")
        cab_filtros.pack(fill="x", padx=18, pady=(14, 0))
        ctk.CTkLabel(cab_filtros, text="Filtros da fila", font=fonte(13, "bold"), text_color=TEXTO).pack(side="left")
        self.btn_filtros = botao_texto(cab_filtros, "Alterar filtros", self._alterar_filtros, cor=AZUL, width=110, height=26)
        self.btn_filtros.pack(side="left", padx=6)
        self.caixa_filtros = ctk.CTkFrame(card, fg_color="transparent")
        self.caixa_filtros.pack(fill="x", padx=18, pady=(4, 2))
        self.lbl_filtros = ctk.CTkLabel(card, text="Valor igual ou acima do limite nunca é aprovado.",
                                        font=fonte(11), text_color=SUAVE, anchor="w")
        self.lbl_filtros.pack(anchor="w", padx=18, pady=(2, 4))

        rodape = ctk.CTkFrame(card, fg_color="transparent")
        rodape.pack(fill="x", padx=18, pady=(4, 14))
        self.sw_simular = ctk.CTkSwitch(rodape, text="Só simular — mostra o que seria aprovado, sem aprovar nada",
                                        font=fonte(12), text_color=TEXTO, progress_color=AZUL,
                                        command=self._atualizar_textos)
        self.sw_simular.pack(anchor="w")

    def _montar_botao_principal(self):
        self.btn_principal = ctk.CTkButton(
            self.miolo, text="", height=56, corner_radius=12, fg_color=AZUL, hover_color=AZUL_ESCURO,
            text_color_disabled="#FFFFFF", font=fonte(17, "bold"), command=self._rodar)
        self.btn_principal.pack(fill="x")
        self.lbl_dica = ctk.CTkLabel(self.miolo, text="", font=fonte(12), text_color=SUAVE)
        self.lbl_dica.pack(pady=(6, 0))

    def _montar_automatico(self):
        card = Cartao(self.miolo)
        card.pack(fill="x", pady=(14, 0))
        linha = ctk.CTkFrame(card, fg_color="transparent")
        linha.pack(fill="x", padx=18, pady=(14, 0))
        self.sw_auto = ctk.CTkSwitch(linha, text="Rodar sozinho a cada", font=fonte(13, "bold"),
                                     text_color=TEXTO, progress_color=VERDE, command=self._alternar_automatico)
        self.sw_auto.pack(side="left")
        self.menu_minutos = ctk.CTkOptionMenu(linha, values=["30 minutos", "60 minutos", "90 minutos", "120 minutos"],
                                              width=120, height=28, fg_color=AZUL_CLARO, button_color=AZUL_CLARO,
                                              button_hover_color=AZUL_HOVER, text_color=AZUL_ESCURO, font=fonte(12),
                                              command=self._mudar_intervalo)
        self.menu_minutos.set(f"{self.auto_minutos} minutos")
        self.menu_minutos.pack(side="left", padx=8)
        self.lbl_proxima = ctk.CTkLabel(linha, text="", font=fonte(12, "bold"), text_color=VERDE)
        self.lbl_proxima.pack(side="right")

        self.ck_comercial = ctk.CTkCheckBox(card, text="Só de segunda a sexta, das 7h às 19h", font=fonte(12),
                                            text_color=TEXTO, checkbox_width=18, checkbox_height=18,
                                            fg_color=AZUL, command=self._mudar_horario)
        if self.auto_horario_comercial:
            self.ck_comercial.select()
        self.ck_comercial.pack(anchor="w", padx=18, pady=(8, 0))
        self.ck_esconder = ctk.CTkCheckBox(card, text="Esconder o navegador nas execuções automáticas",
                                           font=fonte(12), text_color=TEXTO, checkbox_width=18, checkbox_height=18,
                                           fg_color=AZUL, command=self._mudar_esconder)
        if self.auto_esconder:
            self.ck_esconder.select()
        self.ck_esconder.pack(anchor="w", padx=18, pady=(6, 0))
        self.lbl_auto_info = ctk.CTkLabel(card, text="Deixe este programa aberto (pode minimizar). Com o navegador "
                                                     "escondido, a automação trabalha sem aparecer na tela.",
                                          font=fonte(11), text_color=SUAVE, anchor="w", justify="left", wraplength=640)
        self.lbl_auto_info.pack(anchor="w", padx=18, pady=(4, 0))
        self.lbl_historico = ctk.CTkLabel(card, text="", font=fonte(11), text_color=CINZA_TEXTO, anchor="w",
                                          justify="left")
        self.lbl_historico.pack(anchor="w", padx=18, pady=(2, 12))

    # ---------- modo automático ----------
    def _alternar_automatico(self):
        if self.sw_auto.get():
            if self._ler_limite() is None:
                self.sw_auto.deselect()
                return
            modo = "SIMULAR (nada será aprovado)" if self.sw_simular.get() else \
                f"APROVAR de verdade as requisições abaixo de R$ {motor.formatar_brl(self.limite)}"
            if not DialogoConfirmar(
                    self, f"Rodar sozinho a cada {self.auto_minutos} minutos?",
                    f"A cada {self.auto_minutos} minutos o programa vai {modo}, com os filtros: "
                    + "; ".join(motor.descrever_curto(f) for f in self.filtros)
                    + ". A primeira execução é agora.", sim="Ativar", nao="Cancelar", altura=230).resultado:
                self.sw_auto.deselect()
                return
            self.auto_ativo = True
            self._salvar()
            self._disparar_automatico()
        else:
            self.auto_ativo = False
            self.proxima_auto = None
            self._salvar()
            self._mostrar_proxima()

    def _mudar_intervalo(self, escolha):
        self.auto_minutos = int(escolha.split()[0])
        self._salvar()
        if self.auto_ativo and self.proxima_auto and not (self.thread and self.thread.is_alive()):
            self._agendar_proxima()

    def _mudar_horario(self):
        self.auto_horario_comercial = bool(self.ck_comercial.get())
        self._salvar()
        if self.auto_ativo and self.proxima_auto and not (self.thread and self.thread.is_alive()):
            self._agendar_proxima()

    def _mudar_esconder(self):
        self.auto_esconder = bool(self.ck_esconder.get())
        self._salvar()

    def _dentro_do_horario(self, instante):
        if not self.auto_horario_comercial:
            return True
        t = time.localtime(instante)
        return t.tm_wday < 5 and 7 <= t.tm_hour < 19

    def _agendar_proxima(self, primeira=False):
        """Próxima execução: daqui a N minutos (ou 1 min ao abrir o programa), pulando fora do horário."""
        instante = time.time() + (60 if primeira else self.auto_minutos * 60)
        limite = instante + 7 * 24 * 3600
        while not self._dentro_do_horario(instante) and instante < limite:
            instante += 5 * 60
        self.proxima_auto = instante
        self._mostrar_proxima()

    def _mostrar_proxima(self):
        if not self.auto_ativo:
            self.lbl_proxima.configure(text="")
            return
        if self.thread and self.thread.is_alive() and self.execucao_automatica:
            self.lbl_proxima.configure(text="Rodando agora...")
        elif self.proxima_auto:
            quando = time.localtime(self.proxima_auto)
            hoje = time.localtime()
            dia = "" if quando.tm_yday == hoje.tm_yday else time.strftime("%d/%m ", quando)
            self.lbl_proxima.configure(text=f"Próxima: {dia}{time.strftime('%H:%M', quando)}")

    def _vigiar_automatico(self):
        """Confere a cada 15 s se chegou a hora (funciona mesmo depois de o PC hibernar)."""
        if self.auto_ativo and self.proxima_auto and time.time() >= self.proxima_auto:
            if self.thread and self.thread.is_alive():
                self.proxima_auto = time.time() + 60      # ainda rodando: tenta de novo em 1 min
            else:
                self._disparar_automatico()
        self.after(15000, self._vigiar_automatico)

    def _disparar_automatico(self):
        if self.thread and self.thread.is_alive():
            self.proxima_auto = time.time() + 60          # outra execução em andamento: tenta em 1 min
            self._mostrar_proxima()
            return
        self.proxima_auto = None
        self._iniciar(bool(self.sw_simular.get()), automatico=True)

    def _registrar_historico(self, final):
        c = final["contagem"]
        aprovadas = c["aprovada"] + c["seria_aprovada"]
        texto = (f"{time.strftime('%H:%M')} — {aprovadas} {'seriam aprovadas' if final['simular'] else 'aprovadas'}"
                 f" (R$ {motor.formatar_brl(final['total_aprovado'])})")
        if c["acima"]:
            texto += f", {c['acima']} acima do limite"
        if c["erro"]:
            texto += f", {c['erro']} com erro"
        self.historico_auto = ([texto] + self.historico_auto)[:3]
        self.lbl_historico.configure(text="Últimas automáticas:  " + "   ·   ".join(self.historico_auto))

    def _montar_andamento(self):
        self.cartao = Cartao(self.miolo)
        c = self.cartao
        topo = ctk.CTkFrame(c, fg_color="transparent")
        topo.pack(fill="x", padx=18, pady=(16, 0))
        self.lbl_titulo = ctk.CTkLabel(topo, text="", font=fonte(20, "bold"), text_color=TEXTO, anchor="w")
        self.lbl_titulo.pack(side="left")
        self.lbl_relogio = ctk.CTkLabel(topo, text="", font=fonte(12), text_color=SUAVE)
        self.lbl_relogio.pack(side="right")
        self.lbl_sub = ctk.CTkLabel(c, text="", font=fonte(13), text_color=SUAVE, anchor="w",
                                    justify="left", wraplength=640)
        self.lbl_sub.pack(fill="x", padx=18)

        self.barra = ctk.CTkProgressBar(c, height=12, corner_radius=6, progress_color=AZUL, fg_color="#E6EAF0")
        self.barra.set(0)
        self.barra.pack(fill="x", padx=18, pady=(12, 14))

        tiles = ctk.CTkFrame(c, fg_color="transparent")
        tiles.pack(fill="x", padx=18)
        for i in range(3):
            tiles.grid_columnconfigure(i, weight=1, uniform="t")
        self.ct_ok = Contador(tiles, "aprovadas", VERDE, VERDE_CLARO)
        self.ct_acima = Contador(tiles, "acima do limite", AMARELO, AMARELO_CLARO)
        self.ct_erro = Contador(tiles, "com erro", VERMELHO, VERMELHO_CLARO)
        self.contadores = (self.ct_ok, self.ct_acima, self.ct_erro)
        for i, t in enumerate(self.contadores):
            t.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 5, 0 if i == 2 else 5))
        self.lbl_total_valor = ctk.CTkLabel(c, text="", font=fonte(12), text_color=VERDE, anchor="w")
        self.lbl_total_valor.pack(fill="x", padx=18, pady=(8, 0))

        rodape = ctk.CTkFrame(c, fg_color="transparent")
        rodape.pack(fill="x", padx=18, pady=16)
        self.btn_parar = ctk.CTkButton(rodape, text="Parar após esta requisição", width=200, height=36,
                                       corner_radius=8, fg_color="transparent", border_width=1,
                                       border_color=VERMELHO, text_color=VERMELHO,
                                       hover_color=VERMELHO_CLARO, font=fonte(13, "bold"),
                                       command=self._pedir_parada)
        self.btn_aprovar_agora = botao_primario(rodape, "Aprovar de verdade agora", self._aprovar_apos_simulacao,
                                                width=200, height=36)
        self.btn_relatorio = botao_secundario(rodape, "Abrir relatório", self._abrir_relatorio, width=130, height=36)
        self.btn_relatorio.pack(side="right")
        self.btn_prints = botao_secundario(rodape, "Prints dos erros", lambda: abrir_no_windows(motor.ERROS_DIR),
                                           width=130, height=36)

    def _montar_detalhes(self):
        self.btn_detalhes = botao_texto(self.miolo, "Ver detalhes técnicos  ▾", self._alternar_detalhes)
        self.caixa_log = ctk.CTkTextbox(self.miolo, height=220, corner_radius=10, border_width=1,
                                        border_color=BORDA, fg_color=CARTAO, text_color="#374151",
                                        font=ctk.CTkFont(family="Consolas", size=11), wrap="word")
        for tag, cor in (("ok", VERDE), ("erro", VERMELHO), ("aviso", AMARELO), ("titulo", AZUL)):
            self.caixa_log.tag_config(tag, foreground=cor)
        self.caixa_log.configure(state="disabled")

    # ---------- textos que dependem das escolhas ----------
    def _ler_limite(self):
        try:
            valor = motor.parsear_valor(self.ent_limite.get())
            if valor <= 0:
                raise ValueError
        except Exception:
            self.lbl_limite_erro.configure(text="Digite um valor, ex.: 10.000,00")
            self.ent_limite.configure(border_color=VERMELHO)
            return None
        self.limite = valor
        self.lbl_limite_erro.configure(text="")
        self.ent_limite.configure(border_color=BORDA)
        self.ent_limite.delete(0, "end")
        self.ent_limite.insert(0, motor.formatar_brl(valor))
        self._salvar()
        self._atualizar_textos()
        return valor

    def _desenhar_filtros(self):
        for w in self.caixa_filtros.winfo_children():
            w.destroy()
        linha, largura = None, 999
        for f in self.filtros:
            texto = motor.descrever_curto(f)
            if largura + len(texto) > 70:          # quebra a linha quando não cabe
                linha = ctk.CTkFrame(self.caixa_filtros, fg_color="transparent")
                linha.pack(fill="x", anchor="w")
                largura = 0
            largura += len(texto) + 4
            ctk.CTkLabel(linha, text=f"  {texto}  ", font=fonte(12), text_color=AZUL_ESCURO,
                         fg_color=AZUL_CLARO, corner_radius=12, height=26).pack(side="left", padx=(0, 6), pady=2)

    def _atualizar_textos(self):
        self._desenhar_filtros()
        if self.sw_simular.get():
            self.btn_principal.configure(text="Simular aprovação")
        else:
            self.btn_principal.configure(text=f"Aprovar abaixo de R$ {motor.formatar_brl(self.limite)}")
        if not self.ja_logou:
            dica = "Primeira vez? Clique em \"Entrar no Coupa\", lá em cima, antes de começar."
        else:
            dica = "O navegador abre sozinho e trabalha em segundo plano. Pode acompanhar por aqui."
        self.lbl_dica.configure(text=dica)

    def _salvar(self):
        salvar_config({"url": self.url, "limite": self.limite, "filtros": self.filtros,
                       "ja_logou": self.ja_logou, "boas_vindas": self.boas_vindas,
                       "auto_ativo": getattr(self, "auto_ativo", False),
                       "auto_minutos": getattr(self, "auto_minutos", 60),
                       "auto_horario_comercial": getattr(self, "auto_horario_comercial", False),
                       "auto_esconder": getattr(self, "auto_esconder", False)})

    def _primeira_vez(self):
        aprovador = next((f["valor"] for f in self.filtros
                          if f["campo"] == "current_approver_association.fullname"), "")
        self.boas_vindas = True
        self._salvar()
        if not DialogoConfirmar(self, "Bem-vindo!",
                                f"A fila vem filtrada para o aprovador “{aprovador}”. "
                                "Se você é outro aprovador, troque o nome nos filtros.",
                                sim="Está certo", nao="Alterar filtros", altura=210).resultado:
            self._alterar_filtros()

    def _alterar_filtros(self):
        d = DialogoFiltros(self, self.filtros)
        if d.resultado:
            self.filtros = d.resultado
            self._salvar()
            self._atualizar_textos()

    def _abrir_configuracoes(self):
        d = DialogoConfiguracoes(self, self.url)
        if d.resultado:
            self.url = d.resultado
            self._salvar()
            self._atualizar_textos()

    # ---------- login ----------
    def _fazer_login(self):
        if self.thread and self.thread.is_alive():
            return
        if not self.url:
            self._abrir_configuracoes()
            if not self.url:
                return
        url = self.url

        def trabalho():
            try:
                motor.fazer_login(url, lambda: esperar_resposta_da_tela("login"))
                fila_ui.put(("login_ok", None))
            except Exception as erro:
                fila_ui.put(("login_erro", str(erro)))

        self._travar(True, "Aguardando login...")
        self.thread = threading.Thread(target=trabalho, daemon=True)
        self.thread.start()

    # ---------- execução ----------
    def _rodar(self, forcar_real=False):
        if self.thread and self.thread.is_alive():
            return
        if self._ler_limite() is None:
            return
        if not self.url:
            self._abrir_configuracoes()
            if not self.url:
                return
        simular = bool(self.sw_simular.get()) and not forcar_real
        if not self.ja_logou and not DialogoConfirmar(
                self, "Já entrou no Coupa?",
                "Na primeira vez é preciso fazer o login pelo botão \"Entrar no Coupa\". "
                "Se já fez, pode continuar.", sim="Continuar", nao="Voltar").resultado:
            return
        if not simular and not DialogoConfirmar(
                self, "Aprovar de verdade?",
                f"Vou aprovar no Coupa as requisições abaixo de R$ {motor.formatar_brl(self.limite)} "
                "com os filtros: " + "; ".join(motor.descrever_filtro(f) for f in self.filtros)
                + ". As demais ficam como estão.",
                sim="Aprovar", nao="Voltar").resultado:
            return

        self._iniciar(simular, automatico=False)

    def _iniciar(self, simular, automatico):
        self.execucao_automatica = automatico
        self._preparar(simular)
        if automatico:
            self.lbl_titulo.configure(text=f"Execução automática das {time.strftime('%H:%M')}")
        self._mostrar_proxima()
        args = dict(url=self.url, limite=self.limite, filtros=[dict(f) for f in self.filtros], simular=simular,
                    discreto=automatico and self.auto_esconder)

        def trabalho():
            try:
                final = motor.executar(**args, notificar=notificar_tela, parar=self.parar)
                fila_ui.put(("fim", final))
            except Exception as erro:
                traceback.print_exc()
                fila_ui.put(("falhou", motor.motivo_amigavel(erro)))

        self.thread = threading.Thread(target=trabalho, daemon=True)
        self.thread.start()

    def _aprovar_apos_simulacao(self):
        self.sw_simular.deselect()
        self._atualizar_textos()
        self._rodar(forcar_real=True)

    def _preparar(self, simular):
        self.parar.clear()
        self.simulando = simular
        self.contagem = {k: 0 for k in motor.NOMES_RESULTADO}
        self.total_valor = 0.0
        for ct in self.contadores:
            ct.definir(0, animar=False)
        self.ct_ok.configure(fg_color=AZUL_CLARO if simular else VERDE_CLARO)
        self.ct_ok.lbl_legenda.configure(text="seriam aprovadas" if simular else "aprovadas")
        self.lbl_total_valor.configure(text="")
        self.alvo_barra = 0
        self.barra.configure(progress_color=AZUL, mode="indeterminate")
        self.barra.start()
        self.lbl_titulo.configure(text="Abrindo o Coupa...")
        self.lbl_sub.configure(text="Aplicando os filtros da fila de aprovação."
                               + ("  (simulação: nada será aprovado)" if simular else ""))
        self.caixa_log.configure(state="normal")
        self.caixa_log.delete("1.0", "end")
        self.caixa_log.configure(state="disabled")
        for b in (self.btn_aprovar_agora, self.btn_prints):
            b.pack_forget()
        self.btn_parar.configure(state="normal", text="Parar após esta requisição")
        self.btn_parar.pack(side="left")
        self.inicio_execucao = time.time()
        self.lbl_relogio.configure(text="⏱ 00:00")
        self._travar(True)
        if not self.cartao.winfo_ismapped():
            self.cartao.pack(fill="x", pady=(18, 0))
            self.btn_detalhes.pack(pady=(8, 0))

    def _travar(self, travar, texto_botao="Trabalhando..."):
        estado = "disabled" if travar else "normal"
        for w in (self.btn_principal, self.btn_login, self.btn_config, self.btn_filtros, self.ent_limite,
                  self.sw_simular, self.menu_minutos, self.ck_comercial, self.ck_esconder):
            w.configure(state=estado)
        if travar:
            self.btn_principal.configure(text=texto_botao, fg_color=AZUL_DESATIVADO)
        else:
            self.btn_principal.configure(fg_color=AZUL)
            self._atualizar_textos()

    def _pedir_parada(self):
        self.parar.set()
        self.btn_parar.configure(state="disabled", text="Parando após esta requisição...")

    def _ao_fechar(self):
        if self.auto_ativo and not (self.thread and self.thread.is_alive()):
            escolha = DialogoConfirmar(self, "O modo automático está ligado",
                                       "Se fechar, as execuções automáticas param. Para elas continuarem, "
                                       "minimize em vez de fechar.", sim="Minimizar", nao="Fechar mesmo assim").resultado
            if escolha:
                self.iconify()
                return
            self.destroy()
            return
        if self.thread and self.thread.is_alive():
            if not DialogoConfirmar(self, "A automação ainda está rodando",
                                    "Prefira \"Parar após esta requisição\" para não deixar nada pela metade.",
                                    sim="Fechar mesmo assim", nao="Voltar").resultado:
                return
        self.destroy()

    # ---------- eventos do motor ----------
    def _processar_fila(self):
        try:
            for _ in range(300):
                tipo, dado = fila_ui.get_nowait()
                if tipo == "log":
                    self._escrever_log(dado)
                elif tipo == "evento":
                    self._evento(*dado)
                elif tipo == "pedido":
                    self._responder(dado)
                elif tipo == "fim":
                    self._finalizar(dado)
                elif tipo == "falhou":
                    self._falhou(dado)
                elif tipo == "login_ok":
                    self.ja_logou = True
                    self._salvar()
                    self._travar(False)
                    DialogoAviso(self, "Login salvo", "Pronto! Agora é só clicar no botão azul.")
                elif tipo == "login_erro":
                    self._travar(False)
                    DialogoAviso(self, "Não consegui abrir o navegador", dado)
        except queue.Empty:
            pass
        self.after(60, self._processar_fila)

    def _evento(self, evento, d):
        if evento == "lista":
            self.barra.stop()
            self.barra.configure(mode="determinate")
            feitos = sum(self.contagem.values())
            self.alvo_barra = feitos / d["total"] if d["total"] else 0
            self.lbl_titulo.configure(text=f"{feitos} de {d['total']} requisições")
            if d["rodada"] > 1:
                self._log(f"\n↻ Lista recarregada: {d['novos']} requisição(ões) nova(s)\n", "titulo")
        elif evento == "item_inicio":
            self.lbl_titulo.configure(text=f"{d['n'] - 1} de {d['total']} requisições")
            self.lbl_sub.configure(text=f"Agora: requisição {d['req']}")
            self._log(f"\n[{d['n']}/{d['total']}] Requisição {d['req']}\n", "titulo")
        elif evento == "item_fim":
            res = d["resultado"]
            self.contagem[res] += 1
            if res in ("aprovada", "seria_aprovada"):
                self.total_valor += d.get("valor") or 0
            c = self.contagem
            self.ct_ok.definir(c["aprovada"] + c["seria_aprovada"])
            self.ct_acima.definir(c["acima"])
            self.ct_erro.definir(c["erro"])
            palavra = "seriam aprovados" if self.simulando else "aprovados"
            self.lbl_total_valor.configure(text=f"R$ {motor.formatar_brl(self.total_valor)} {palavra}"
                                           + (f"  ·  {c['sem_botao']} sem botão de aprovação" if c["sem_botao"] else ""))
            self.alvo_barra = d["n"] / d["total"]
            self.lbl_titulo.configure(text=f"{d['n']} de {d['total']} requisições")
            valor = f"R$ {motor.formatar_brl(d['valor'])}" if d.get("valor") is not None else ""
            textos = {"aprovada": (f"✔ aprovada  {valor}", "ok"),
                      "seria_aprovada": (f"✔ seria aprovada  {valor}", "ok"),
                      "acima": (f"• acima do limite  {valor}", "aviso"),
                      "sem_botao": ("• sem botão de aprovação", None),
                      "erro": (f"✘ {d.get('motivo', '')}", "erro")}
            texto, tag = textos[res]
            self._log(f"  {texto}\n", tag)
            if res != "erro" and d.get("motivo"):
                self._log(f"    ({d['motivo']})\n")
            self._estimar_termino(d["n"], d["total"])
        elif evento == "aviso":
            self._log(f"⚠  {d['texto']}\n", "aviso")

    def _estimar_termino(self, feitos, total):
        if not self.inicio_execucao or feitos == 0 or feitos >= total:
            return
        media = (time.time() - self.inicio_execucao) / feitos
        hora = time.strftime("%H:%M", time.localtime(time.time() + media * (total - feitos)))
        atual = self.lbl_sub.cget("text").split("   ·   Termina")[0]
        self.lbl_sub.configure(text=f"{atual}   ·   Termina por volta das {hora}")

    def _responder(self, pedido):
        if pedido["tipo"] == "login":
            DialogoConfirmar(self, "Faça o login no Coupa",
                             "Entre com seu usuário na janela do navegador que abriu. "
                             "Quando a tela inicial do Coupa aparecer, clique em \"Já entrei\".",
                             sim="Já entrei", nao=None, altura=210)
            pedido["resposta"] = True
        pedido["evento"].set()

    def _finalizar(self, final):
        self._encerrar_execucao()
        self.ultimo_resultado = final
        c = final["contagem"]
        aprovadas = c["aprovada"] + c["seria_aprovada"]
        valor = motor.formatar_brl(final["total_aprovado"])
        if final["sessao_expirada"]:
            self.barra.configure(progress_color=AMARELO)
            self.lbl_titulo.configure(text="A sessão do Coupa expirou")
            self.lbl_sub.configure(text="Clique em \"Entrar no Coupa\", faça o login e rode de novo.")
            self.ja_logou = False
            self._salvar()
        elif final["interrompido"]:
            self.lbl_titulo.configure(text="Parado")
            self.lbl_sub.configure(text=f"{aprovadas} aprovada(s) até aqui (R$ {valor}).")
        elif not any(c.values()):
            self.barra.configure(progress_color=VERDE)
            self.alvo_barra = 1.0
            self.lbl_titulo.configure(text="Fila vazia  ✓")
            self.lbl_sub.configure(text="Nenhuma requisição pendente de aprovação com esses filtros.")
        elif final["simular"]:
            self.barra.configure(progress_color=AZUL)
            self.alvo_barra = 1.0
            self.lbl_titulo.configure(text=f"Simulação: {aprovadas} seriam aprovadas")
            self.lbl_sub.configure(text=f"Total de R$ {valor}. {c['acima']} ficariam para análise manual. "
                                        "Nada foi aprovado — confira o relatório.")
            if aprovadas:
                self.btn_aprovar_agora.pack(side="left")
        else:
            self.barra.configure(progress_color=VERDE if not c["erro"] else AMARELO)
            self.alvo_barra = 1.0
            self.lbl_titulo.configure(text=f"Pronto!  {aprovadas} aprovadas  ✓" if not c["erro"]
                                      else f"Terminou — {c['erro']} com erro")
            partes = [f"R$ {valor} aprovados"]
            if c["acima"]:
                partes.append(f"{c['acima']} acima do limite ficaram para você")
            if c["erro"]:
                partes.append(f"{c['erro']} não foram aprovadas por erro (veja o relatório)")
            self.lbl_sub.configure(text=". ".join(partes) + ".")
        if c["erro"]:
            self.btn_prints.pack(side="right", padx=8)
        self._atualizar_textos()
        if self.execucao_automatica:
            self._registrar_historico(final)
            if final["sessao_expirada"]:
                # sem login não adianta continuar tentando: desliga e avisa
                self.auto_ativo = False
                self.sw_auto.deselect()
                self._salvar()
                self._mostrar_proxima()
                self._chamar_atencao()
                DialogoAviso(self, "Execução automática pausada",
                             "A sessão do Coupa expirou. Faça o login de novo pelo botão \"Entrar no Coupa\" "
                             "e ligue \"Rodar sozinho\" outra vez.")
            elif self.auto_ativo and not final["interrompido"]:
                self._agendar_proxima()
            elif final["interrompido"]:
                self.auto_ativo = False
                self.sw_auto.deselect()
                self._salvar()
                self._mostrar_proxima()
            # execução automática sem problema: não interrompe quem está usando o PC
        else:
            if self.auto_ativo:
                self._agendar_proxima()
            self._chamar_atencao()

    def _falhou(self, motivo):
        self._encerrar_execucao()
        if self.execucao_automatica and self.auto_ativo:
            self.historico_auto = ([f"{time.strftime('%H:%M')} — falhou: {motivo}"] + self.historico_auto)[:3]
            self.lbl_historico.configure(text="Últimas automáticas:  " + "   ·   ".join(self.historico_auto))
            self._agendar_proxima()          # tenta de novo no próximo horário
        self.barra.configure(progress_color=VERMELHO)
        self.lbl_titulo.configure(text="Algo deu errado")
        self.lbl_sub.configure(text=f"{motivo}\nSe precisar, abra \"Ver detalhes técnicos\" e tire um print.")
        self._chamar_atencao()

    def _encerrar_execucao(self):
        self.barra.stop()
        self.barra.configure(mode="determinate")
        self.barra.set(self.alvo_barra)
        self.btn_parar.pack_forget()
        self._travar(False)
        if self.inicio_execucao:
            self.lbl_relogio.configure(text=f"⏱ {formatar_tempo(time.time() - self.inicio_execucao)}")
        self.inicio_execucao = None

    def _chamar_atencao(self):
        self.bell()
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(400, lambda: self.attributes("-topmost", False))

    def _abrir_relatorio(self):
        if self.ultimo_resultado and self.ultimo_resultado.get("relatorio"):
            abrir_no_windows(self.ultimo_resultado["relatorio"])
            return
        relatorios = sorted(motor.RESULTADOS_DIR.glob("aprovacoes_*.xlsx"), key=os.path.getmtime) \
            if motor.RESULTADOS_DIR.exists() else []
        if relatorios:
            abrir_no_windows(relatorios[-1])
        else:
            DialogoAviso(self, "Relatório", "O relatório aparece aqui quando a automação terminar.")

    # ---------- log, animação, relógio ----------
    def _log(self, texto, tag=None):
        self.caixa_log.configure(state="normal")
        self.caixa_log.insert("end", texto, tag)
        self.caixa_log.see("end")
        self.caixa_log.configure(state="disabled")

    def _escrever_log(self, texto):
        for linha in texto.splitlines(keepends=True):
            tag = "aviso" if "⚠" in linha else "erro" if "Erro" in linha else None
            self._log(linha, tag)

    def _alternar_detalhes(self):
        if self.caixa_log.winfo_ismapped():
            self.caixa_log.pack_forget()
            self.btn_detalhes.configure(text="Ver detalhes técnicos  ▾")
        else:
            self.caixa_log.pack(fill="both", expand=True, pady=(4, 0))
            self.btn_detalhes.configure(text="Esconder detalhes técnicos  ▴")
            self.after(50, lambda: self.corpo._parent_canvas.yview_moveto(1.0))

    def _animar(self):
        if self.barra.cget("mode") == "determinate":
            atual = self.barra.get()
            if abs(self.alvo_barra - atual) > 0.002:
                self.barra.set(atual + (self.alvo_barra - atual) * 0.18)
        for ct in self.contadores:
            ct.passo()
        self.after(16, self._animar)

    def _relogio(self):
        if self.inicio_execucao:
            self.lbl_relogio.configure(text=f"⏱ {formatar_tempo(time.time() - self.inicio_execucao)}")
        self.after(1000, self._relogio)


# =====================================================================
#                              JANELAS
# =====================================================================
class DialogoBase(ctk.CTkToplevel):
    def __init__(self, pai, titulo, largura, altura):
        super().__init__(pai, fg_color=FUNDO)
        self.title(titulo)
        self.resizable(False, False)
        self.resultado = None
        self.transient(pai)
        self.after(250, lambda: aplicar_icone(self))
        pai.update_idletasks()
        x = pai.winfo_rootx() + (pai.winfo_width() - largura) // 2
        y = pai.winfo_rooty() + max(40, (pai.winfo_height() - altura) // 3)
        self.geometry(f"{largura}x{altura}+{max(0, x)}+{max(0, y)}")
        self.bind("<Escape>", lambda _: self.destroy())

    def _esperar(self):
        self.lift()
        self.after(50, self.grab_set)
        self.wait_window()


class DialogoConfirmar(DialogoBase):
    def __init__(self, pai, titulo, texto, sim="OK", nao="Cancelar", largura=460, altura=200):
        super().__init__(pai, titulo, largura, altura)
        ctk.CTkLabel(self, text=titulo, font=fonte(17, "bold"), text_color=TEXTO,
                     anchor="w").pack(fill="x", padx=24, pady=(22, 6))
        ctk.CTkLabel(self, text=texto, font=fonte(13), text_color=SUAVE, justify="left",
                     anchor="w", wraplength=largura - 48).pack(fill="x", padx=24)
        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(side="bottom", fill="x", padx=24, pady=20)
        btn_sim = botao_primario(botoes, sim, self._sim, width=max(110, 9 * len(sim)))
        btn_sim.pack(side="right")
        if nao:
            botao_texto(botoes, nao, self.destroy, height=38, width=100).pack(side="right", padx=8)
        self.bind("<Return>", lambda _: self._sim())
        self.after(100, btn_sim.focus_set)
        self._esperar()

    def _sim(self):
        self.resultado = True
        self.destroy()


class DialogoAviso(DialogoConfirmar):
    def __init__(self, pai, titulo, texto):
        super().__init__(pai, titulo, texto, sim="Entendi", nao=None, altura=190)


class DialogoConfiguracoes(DialogoBase):
    def __init__(self, pai, url):
        super().__init__(pai, "Configurações", 580, 330)
        ctk.CTkLabel(self, text="Configurações", font=fonte(17, "bold"),
                     text_color=TEXTO).pack(anchor="w", padx=24, pady=(22, 8))
        ctk.CTkLabel(self, text="Endereço do Coupa", font=fonte(12, "bold"), text_color=TEXTO).pack(anchor="w", padx=24)
        ctk.CTkLabel(self, text="Já vem preenchido. Só mude se o endereço do Coupa mudar.",
                     font=fonte(11), text_color=SUAVE).pack(anchor="w", padx=24)
        self.ent_url = ctk.CTkEntry(self, height=34, corner_radius=8)
        self.ent_url.insert(0, url or motor.COUPA_URL)
        self.ent_url.pack(fill="x", padx=24, pady=(4, 0))
        self.lbl_erro = ctk.CTkLabel(self, text="", font=fonte(12), text_color=VERMELHO)
        self.lbl_erro.pack(anchor="w", padx=24)

        ctk.CTkLabel(self, text="Navegador da automação", font=fonte(12, "bold"),
                     text_color=TEXTO).pack(anchor="w", padx=24, pady=(6, 0))
        linha = ctk.CTkFrame(self, fg_color="transparent")
        linha.pack(fill="x", padx=24, pady=(4, 0))
        botao_secundario(linha, "Limpar cache", self._limpar_cache, width=120, height=32).pack(side="left")
        self.lbl_cache = ctk.CTkLabel(linha, text="Use se a lista vier desatualizada. O login continua salvo.",
                                      font=fonte(11), text_color=SUAVE)
        self.lbl_cache.pack(side="left", padx=10)

        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(side="bottom", fill="x", padx=24, pady=18)
        botao_primario(botoes, "Salvar", self._salvar, width=110).pack(side="right")
        botao_texto(botoes, "Cancelar", self.destroy, height=38, width=90).pack(side="right", padx=8)
        botao_texto(botoes, "Voltar ao padrão", self._padrao, cor=AZUL, height=38, width=130).pack(side="left")
        self.bind("<Return>", lambda _: self._salvar())
        self._esperar()

    def _limpar_cache(self):
        try:
            removidos = motor.limpar_cache_navegador()
            texto = "Cache limpo ✓ — o login continua salvo." if removidos else "O cache já estava limpo."
            self.lbl_cache.configure(text=texto, text_color=VERDE)
        except Exception as erro:
            self.lbl_cache.configure(text=f"Não consegui limpar: feche o navegador da automação ({erro})",
                                     text_color=VERMELHO)

    def _padrao(self):
        self.ent_url.delete(0, "end")
        self.ent_url.insert(0, motor.COUPA_URL)

    def _salvar(self):
        url = self.ent_url.get().strip()
        if not re.match(r"https?://[^/]+\.[^/]+", url):
            self.lbl_erro.configure(text="Cole o endereço completo, começando com https://")
            return
        self.resultado = url
        self.destroy()


class DialogoFiltros(DialogoBase):
    """Edita os filtros da fila. Os campos vêm de motor.CAMPOS_DISPONIVEIS."""
    def __init__(self, pai, filtros):
        super().__init__(pai, "Filtros da fila", 640, 430)
        self.filtros = [dict(f) for f in filtros]
        ctk.CTkLabel(self, text="Filtros da fila de aprovação", font=fonte(17, "bold"),
                     text_color=TEXTO).pack(anchor="w", padx=24, pady=(22, 2))
        ctk.CTkLabel(self, text="Entram na fila só as requisições que atendem a TODOS os filtros. "
                                "Solicitado por e Status são obrigatórios.",
                     font=fonte(12), text_color=SUAVE, wraplength=590, justify="left").pack(anchor="w", padx=24, pady=(0, 10))
        self.lista = Cartao(self)
        self.lista.pack(fill="x", padx=24)
        self.lista.grid_columnconfigure(2, weight=1)
        self.lbl_erro = ctk.CTkLabel(self, text="", font=fonte(12), text_color=VERMELHO, wraplength=590,
                                     justify="left")
        self.lbl_erro.pack(anchor="w", padx=24, pady=(6, 0))
        livres = [c for c in motor.CAMPOS_DISPONIVEIS if c not in {f["campo"] for f in self.filtros}]
        ctk.CTkLabel(self, text="Outros campos do Coupa (centro de custo, valor, data...) entram aqui "
                                "quando a lista de opções for incluída." if not livres else "",
                     font=fonte(11), text_color=SUAVE, wraplength=590, justify="left").pack(anchor="w", padx=24)
        botoes = ctk.CTkFrame(self, fg_color="transparent")
        botoes.pack(side="bottom", fill="x", padx=24, pady=18)
        botao_primario(botoes, "Salvar", self._salvar, width=110).pack(side="right")
        botao_texto(botoes, "Cancelar", self.destroy, height=38, width=90).pack(side="right", padx=8)
        botao_texto(botoes, "Voltar ao padrão", self._padrao, cor=AZUL, height=38, width=130).pack(side="left")
        self._desenhar()
        self._esperar()

    def _desenhar(self):
        for w in self.lista.winfo_children():
            w.destroy()
        self.campos_valor = []
        for r, f in enumerate(self.filtros):
            info = motor.CAMPOS_DISPONIVEIS.get(f["campo"], {"rotulo": f["campo"], "tipo": "texto"})
            pad = (12 if r == 0 else 6, 12 if r == len(self.filtros) - 1 else 6)
            ctk.CTkLabel(self.lista, text=info["rotulo"], font=fonte(13, "bold"), text_color=TEXTO,
                         width=180, anchor="w").grid(row=r, column=0, sticky="w", padx=(14, 6), pady=pad)
            if info["tipo"] == "lista":
                opcoes = info.get("opcoes", {})
                ctk.CTkLabel(self.lista, text="é", font=fonte(12), text_color=SUAVE, width=70).grid(row=r, column=1, pady=pad)
                menu = ctk.CTkOptionMenu(self.lista, values=list(opcoes.values()) or [f["valor"]], height=32,
                                         fg_color=AZUL_CLARO, button_color=AZUL_CLARO, button_hover_color=AZUL_HOVER,
                                         text_color=AZUL_ESCURO, font=fonte(12),
                                         state="normal" if len(opcoes) > 1 else "disabled")
                menu.set(opcoes.get(f["valor"], f["valor"]))
                menu.grid(row=r, column=2, sticky="ew", padx=(0, 14), pady=pad)
                self.campos_valor.append(("lista", menu, opcoes))
            else:
                ctk.CTkLabel(self.lista, text=motor.CONDICOES.get(f.get("condicao", "con"), "contém"),
                             font=fonte(12), text_color=SUAVE, width=70).grid(row=r, column=1, pady=pad)
                e = ctk.CTkEntry(self.lista, height=32, corner_radius=8)
                e.insert(0, f.get("valor", ""))
                e.grid(row=r, column=2, sticky="ew", padx=(0, 14), pady=pad)
                self.campos_valor.append(("texto", e, None))

    def _padrao(self):
        self.filtros = [dict(f) for f in motor.FILTROS_PADRAO]
        self._desenhar()
        self.lbl_erro.configure(text="")

    def _salvar(self):
        novos = []
        for f, (tipo, w, opcoes) in zip(self.filtros, self.campos_valor):
            if tipo == "lista":
                escolhido = w.get()
                valor = next((k for k, v in opcoes.items() if v == escolhido), escolhido)
            else:
                valor = " ".join(w.get().split())
            novos.append({**f, "valor": valor})
        problemas = motor.validar_filtros(novos)
        if problemas:
            self.lbl_erro.configure(text="  ·  ".join(problemas))
            return
        self.resultado = novos
        self.destroy()


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Automacoes.AprovacoesCoupa")
        except Exception:
            pass
    App().mainloop()
