# -*- coding: utf-8 -*-
"""Dashboard Desktop (estilo Windows Forms) para Automação Microsoft Rewards com Relatório de Erros."""

import csv
import json
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime

from automation import AutomationConfig, ActionReport, RewardsAutomationEngine

CONFIG_FILE = "config_painel.json"


class RewardsDashboardApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Automação Microsoft Rewards - Dashboard & Diagnóstico de Erros")
        self.geometry("1120x740")
        self.minsize(980, 660)
        self.configure(bg="#F0F2F5")

        self.all_reports: list[ActionReport] = []
        self.filtro_atual = tk.StringVar(value="TODOS")

        # Variáveis de configuração do formulário (carregadas do config_painel.json local, ignorado pelo Git)
        self.var_email = tk.StringVar(value="")
        self.var_senha = tk.StringVar(value="")
        self.var_qtd_pesquisas = tk.IntVar(value=30)
        self.var_tempo_pagina = tk.DoubleVar(value=7.0)
        self.var_intervalo_teclado = tk.DoubleVar(value=10.0)
        self.var_atraso_tecla = tk.IntVar(value=85)
        self.var_variacao_humana = tk.BooleanVar(value=True)
        self.var_espaco_final = tk.BooleanVar(value=True)
        self.var_cards_diarios = tk.BooleanVar(value=True)
        self.var_fazer_pesquisas = tk.BooleanVar(value=True)

        self._carregar_config_salva()

        self.engine = RewardsAutomationEngine(
            on_report=self._on_engine_report,
            on_status_change=self._on_engine_status,
            on_progress=self._on_engine_progress,
        )

        self._configurar_estilos()
        self._construir_interface()
        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)

    def _configurar_estilos(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("Treeview", font=("Segoe UI", 9), rowheight=26, background="#FFFFFF", fieldbackground="#FFFFFF")
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background="#E4E7EB", foreground="#1F2937")
        style.map("Treeview", background=[("selected", "#2563EB")], foreground=[("selected", "#FFFFFF")])

    def _construir_interface(self):
        # 1. Cabeçalho Superior
        header = tk.Frame(self, bg="#1E293B", height=58, padx=18, pady=10)
        header.pack(fill="x")

        tk.Label(
            header,
            text="Painel de Automação & Diagnóstico (Fluxo Humano)",
            font=("Segoe UI", 14, "bold"),
            bg="#1E293B",
            fg="#FFFFFF",
        ).pack(side="left")

        self.lbl_badge_status = tk.Label(
            header,
            text="● PARADO",
            font=("Segoe UI", 10, "bold"),
            bg="#334155",
            fg="#F8FAFC",
            padx=12,
            pady=4,
        )
        self.lbl_badge_status.pack(side="right")

        # 2. Cards de Indicadores (KPIs)
        kpi_frame = tk.Frame(self, bg="#F0F2F5", padx=14, pady=10)
        kpi_frame.pack(fill="x")
        for i in range(4):
            kpi_frame.columnconfigure(i, weight=1)

        self.lbl_kpi_status = self._criar_card_kpi(kpi_frame, 0, "STATUS DO FLUXO", "Aguardando Início", "#2563EB")
        self.lbl_kpi_pesquisas = self._criar_card_kpi(kpi_frame, 1, "PESQUISAS COMPUTADAS", "0 / 30", "#059669")
        self.lbl_kpi_cards = self._criar_card_kpi(kpi_frame, 2, "CARDS / ATIVIDADES (7s)", "0", "#7C3AED")
        self.lbl_kpi_erros = self._criar_card_kpi(kpi_frame, 3, "ERROS / FALHAS DETECTADAS", "0", "#DC2626")

        # 3. Painel de Configuração + Botões de Controle (Estilo Windows Forms GroupBox)
        mid_container = tk.Frame(self, bg="#F0F2F5", padx=14, pady=2)
        mid_container.pack(fill="x")

        grp_config = tk.LabelFrame(
            mid_container,
            text=" Parâmetros de Tempo e Comportamento Humano (Ajuste Fino) ",
            font=("Segoe UI", 10, "bold"),
            bg="#FFFFFF",
            fg="#1E293B",
            padx=14,
            pady=10,
            bd=1,
            relief="solid",
        )
        grp_config.pack(side="left", fill="both", expand=True, padx=(0, 8))

        # Linha 1 de configurações (E-mail, Senha, Qtd. Pesquisas, Velocidade Teclado)
        tk.Label(grp_config, text="E-mail Microsoft:", font=("Segoe UI", 9, "bold"), bg="#FFFFFF").grid(
            row=0, column=0, sticky="w", pady=4
        )
        tk.Entry(grp_config, textvariable=self.var_email, width=23, font=("Segoe UI", 9), bd=1, relief="solid").grid(
            row=0, column=1, sticky="w", padx=(6, 12), pady=4
        )

        tk.Label(grp_config, text="Senha:", font=("Segoe UI", 9, "bold"), bg="#FFFFFF").grid(
            row=0, column=2, sticky="w", pady=4
        )
        tk.Entry(grp_config, textvariable=self.var_senha, width=15, font=("Segoe UI", 9), bd=1, relief="solid").grid(
            row=0, column=3, sticky="w", padx=(6, 12), pady=4
        )

        tk.Label(grp_config, text="Qtd. Pesquisas:", font=("Segoe UI", 9), bg="#FFFFFF").grid(
            row=0, column=4, sticky="w", pady=4
        )
        tk.Spinbox(grp_config, from_=1, to=100, textvariable=self.var_qtd_pesquisas, width=6, font=("Segoe UI", 9)).grid(
            row=0, column=5, sticky="w", padx=(6, 4), pady=4
        )

        # Linha 2 de configurações (7s na página, 10s no teclado e Velocidade ms)
        tk.Label(
            grp_config,
            text="Permanência na Pesquisa (s):",
            font=("Segoe UI", 9, "bold"),
            fg="#0F172A",
            bg="#FFFFFF",
        ).grid(row=1, column=0, sticky="w", pady=6)
        tk.Spinbox(
            grp_config,
            from_=1.0,
            to=60.0,
            increment=0.5,
            textvariable=self.var_tempo_pagina,
            width=8,
            font=("Segoe UI", 9, "bold"),
        ).grid(row=1, column=1, sticky="w", padx=(6, 12), pady=6)

        tk.Label(
            grp_config,
            text="Intervalo entre Pesquisas (s):",
            font=("Segoe UI", 9, "bold"),
            fg="#0F172A",
            bg="#FFFFFF",
        ).grid(row=1, column=2, sticky="w", pady=6)
        tk.Spinbox(
            grp_config,
            from_=1.0,
            to=120.0,
            increment=0.5,
            textvariable=self.var_intervalo_teclado,
            width=8,
            font=("Segoe UI", 9, "bold"),
        ).grid(row=1, column=3, sticky="w", padx=(6, 12), pady=6)

        tk.Label(grp_config, text="Velocidade Teclado (ms):", font=("Segoe UI", 9), bg="#FFFFFF").grid(
            row=1, column=4, sticky="w", pady=6
        )
        tk.Spinbox(grp_config, from_=30, to=350, increment=5, textvariable=self.var_atraso_tecla, width=6, font=("Segoe UI", 9)).grid(
            row=1, column=5, sticky="w", padx=(6, 4), pady=6
        )

        # Linha 3 de checkboxes
        chk_frame = tk.Frame(grp_config, bg="#FFFFFF")
        chk_frame.grid(row=2, column=0, columnspan=6, sticky="w", pady=(4, 0))

        tk.Checkbutton(
            chk_frame,
            text="Fazer todas as Missões do Rewards (Novo Dashboard / Ganhar / Conjunto Diário)",
            variable=self.var_cards_diarios,
            bg="#FFFFFF",
            fg="#0F172A",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", padx=(0, 12))

        tk.Checkbutton(
            chk_frame,
            text="Fazer Pesquisas no Bing (pula se já concluídas)",
            variable=self.var_fazer_pesquisas,
            bg="#FFFFFF",
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(0, 12))

        tk.Checkbutton(
            chk_frame,
            text="Espaço no final da pesquisa",
            variable=self.var_espaco_final,
            bg="#FFFFFF",
            font=("Segoe UI", 9),
        ).pack(side="left")

        # Painel de Botões de Ação à direita
        grp_acoes = tk.LabelFrame(
            mid_container,
            text=" Controle de Execução ",
            font=("Segoe UI", 10, "bold"),
            bg="#FFFFFF",
            fg="#1E293B",
            padx=12,
            pady=10,
            bd=1,
            relief="solid",
        )
        grp_acoes.pack(side="right", fill="y")

        self.btn_iniciar = tk.Button(
            grp_acoes,
            text="▶  INICIAR AUTOMAÇÃO",
            font=("Segoe UI", 10, "bold"),
            bg="#16A34A",
            fg="#FFFFFF",
            activebackground="#15803D",
            activeforeground="#FFFFFF",
            relief="flat",
            cursor="hand2",
            width=24,
            pady=7,
            command=self.iniciar_automacao,
        )
        self.btn_iniciar.pack(pady=(0, 6))

        self.btn_parar = tk.Button(
            grp_acoes,
            text="⏹  PARAR EXECUÇÃO",
            font=("Segoe UI", 9, "bold"),
            bg="#DC2626",
            fg="#FFFFFF",
            activebackground="#B91C1C",
            activeforeground="#FFFFFF",
            relief="flat",
            cursor="hand2",
            width=24,
            pady=5,
            state="disabled",
            command=self.parar_automacao,
        )
        self.btn_parar.pack(pady=(0, 6))

        self.btn_login = tk.Button(
            grp_acoes,
            text="🔑 1. Abrir Perfil / Login Manual",
            font=("Segoe UI", 9),
            bg="#2563EB",
            fg="#FFFFFF",
            activebackground="#1D4ED8",
            activeforeground="#FFFFFF",
            relief="flat",
            cursor="hand2",
            width=24,
            pady=4,
            command=self.abrir_login_manual,
        )
        self.btn_login.pack()

        # 4. Barra de Progresso
        prog_frame = tk.Frame(self, bg="#F0F2F5", padx=14, pady=6)
        prog_frame.pack(fill="x")
        self.progressbar = ttk.Progressbar(prog_frame, orient="horizontal", mode="determinate")
        self.progressbar.pack(fill="x")

        # 5. Tabela de Relatórios e Diagnóstico de Erros
        table_container = tk.LabelFrame(
            self,
            text=" Relatório de Execução e Diagnóstico de Erros (Por que uma ação não pôde ser realizada) ",
            font=("Segoe UI", 10, "bold"),
            bg="#FFFFFF",
            fg="#1E293B",
            padx=12,
            pady=8,
            bd=1,
            relief="solid",
        )
        table_container.pack(fill="both", expand=True, padx=14, pady=(2, 12))

        # Barra de filtros e exportação
        toolbar = tk.Frame(table_container, bg="#FFFFFF")
        toolbar.pack(fill="x", pady=(0, 6))

        tk.Label(toolbar, text="Filtrar visualização:", font=("Segoe UI", 9, "bold"), bg="#FFFFFF").pack(side="left", padx=(0, 8))

        for rotulo, valor in [
            ("Todos os Eventos", "TODOS"),
            ("Somente Erros / Falhas", "ERRO"),
            ("Avisos / Bloqueios", "AVISO"),
            ("Somente Sucessos", "SUCESSO"),
        ]:
            tk.Radiobutton(
                toolbar,
                text=rotulo,
                variable=self.filtro_atual,
                value=valor,
                bg="#FFFFFF",
                font=("Segoe UI", 9),
                command=self._atualizar_tabela_filtrada,
            ).pack(side="left", padx=4)

        tk.Button(
            toolbar,
            text="🗑 Limpar Relatório",
            font=("Segoe UI", 9),
            bg="#F1F5F9",
            fg="#334155",
            relief="solid",
            bd=1,
            padx=8,
            cursor="hand2",
            command=self.limpar_relatorio,
        ).pack(side="right", padx=(6, 0))

        tk.Button(
            toolbar,
            text="📄 Exportar CSV",
            font=("Segoe UI", 9),
            bg="#F1F5F9",
            fg="#334155",
            relief="solid",
            bd=1,
            padx=8,
            cursor="hand2",
            command=self.exportar_csv,
        ).pack(side="right")

        # Treeview com barra de rolagem
        tree_frame = tk.Frame(table_container, bg="#FFFFFF")
        tree_frame.pack(fill="both", expand=True)

        colunas = ("horario", "acao", "etapa", "status", "duracao", "motivo")
        self.tree = ttk.Treeview(tree_frame, columns=colunas, show="headings", selectmode="browse")

        self.tree.heading("horario", text="Horário")
        self.tree.heading("acao", text="Ação / Pesquisa")
        self.tree.heading("etapa", text="Etapa do Fluxo")
        self.tree.heading("status", text="Status")
        self.tree.heading("duracao", text="Tempo (s)")
        self.tree.heading("motivo", text="Relatório / Motivo Detalhado (Sucesso ou Causa do Erro)")

        self.tree.column("horario", width=75, anchor="center", stretch=False)
        self.tree.column("acao", width=220, anchor="w", stretch=False)
        self.tree.column("etapa", width=155, anchor="w", stretch=False)
        self.tree.column("status", width=90, anchor="center", stretch=False)
        self.tree.column("duracao", width=75, anchor="center", stretch=False)
        self.tree.column("motivo", width=440, anchor="w", stretch=True)

        # Cores por tipo de linha
        self.tree.tag_configure("SUCESSO", background="#ECFDF5", foreground="#065F46")
        self.tree.tag_configure("ERRO", background="#FEF2F2", foreground="#991B1B")
        self.tree.tag_configure("AVISO", background="#FFFBEB", foreground="#92400E")
        self.tree.tag_configure("INFO", background="#EFF6FF", foreground="#1E40AF")

        scrollbar_y = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar_y.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar_y.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._ao_selecionar_linha)

        # Caixa de inspeção detalhada do motivo na parte inferior
        detalhe_frame = tk.Frame(table_container, bg="#F8FAFC", bd=1, relief="solid", padx=8, pady=6)
        detalhe_frame.pack(fill="x", pady=(6, 0))

        tk.Label(
            detalhe_frame,
            text="Diagnóstico da Linha Selecionada:",
            font=("Segoe UI", 9, "bold"),
            bg="#F8FAFC",
            fg="#334155",
        ).pack(side="left", padx=(0, 6))

        self.lbl_detalhe_erro = tk.Label(
            detalhe_frame,
            text="Clique em qualquer registro da tabela acima para visualizar o motivo completo aqui.",
            font=("Segoe UI", 9),
            bg="#F8FAFC",
            fg="#0F172A",
            anchor="w",
            justify="left",
        )
        self.lbl_detalhe_erro.pack(side="left", fill="x", expand=True)

    def _criar_card_kpi(self, parent, col: int, titulo: str, valor_inicial: str, cor_destaque: str) -> tk.Label:
        card = tk.Frame(parent, bg="#FFFFFF", bd=1, relief="solid", padx=12, pady=8)
        card.grid(row=0, column=col, sticky="nsew", padx=4)

        tk.Label(card, text=titulo, font=("Segoe UI", 8, "bold"), bg="#FFFFFF", fg="#64748B").pack(anchor="w")
        lbl_valor = tk.Label(card, text=valor_inicial, font=("Segoe UI", 14, "bold"), bg="#FFFFFF", fg=cor_destaque)
        lbl_valor.pack(anchor="w", pady=(2, 0))
        return lbl_valor

    def _obter_config_atual(self) -> AutomationConfig:
        cfg = AutomationConfig(
            email=self.var_email.get().strip(),
            senha=self.var_senha.get().strip(),
            quantidade_pesquisas=max(1, int(self.var_qtd_pesquisas.get())),
            tempo_pagina_segundos=max(1.0, float(self.var_tempo_pagina.get())),
            intervalo_teclado_segundos=max(1.0, float(self.var_intervalo_teclado.get())),
            atraso_tecla_ms=max(20, int(self.var_atraso_tecla.get())),
            usar_variacao_humana=bool(self.var_variacao_humana.get()),
            espaco_final_pesquisa=bool(self.var_espaco_final.get()),
            executar_cards_diarios=bool(self.var_cards_diarios.get()),
            executar_pesquisas_bing=bool(self.var_fazer_pesquisas.get()),
        )
        self._salvar_config(cfg)
        return cfg

    def _salvar_config(self, cfg: AutomationConfig):
        dados = {
            "email": cfg.email,
            "senha": cfg.senha,
            "quantidade_pesquisas": cfg.quantidade_pesquisas,
            "tempo_pagina_segundos": cfg.tempo_pagina_segundos,
            "intervalo_teclado_segundos": cfg.intervalo_teclado_segundos,
            "atraso_tecla_ms": cfg.atraso_tecla_ms,
            "usar_variacao_humana": cfg.usar_variacao_humana,
            "espaco_final_pesquisa": cfg.espaco_final_pesquisa,
            "executar_cards_diarios": cfg.executar_cards_diarios,
            "executar_pesquisas_bing": cfg.executar_pesquisas_bing,
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(dados, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _carregar_config_salva(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                dados = json.load(f)
            self.var_email.set(dados.get("email", ""))
            self.var_senha.set(dados.get("senha", ""))
            self.var_qtd_pesquisas.set(int(dados.get("quantidade_pesquisas", 30)))
            self.var_tempo_pagina.set(float(dados.get("tempo_pagina_segundos", 7.0)))
            self.var_intervalo_teclado.set(float(dados.get("intervalo_teclado_segundos", 10.0)))
            self.var_atraso_tecla.set(int(dados.get("atraso_tecla_ms", 85)))
            self.var_variacao_humana.set(bool(dados.get("usar_variacao_humana", True)))
            self.var_espaco_final.set(bool(dados.get("espaco_final_pesquisa", True)))
            self.var_cards_diarios.set(bool(dados.get("executar_cards_diarios", True)))
            self.var_fazer_pesquisas.set(bool(dados.get("executar_pesquisas_bing", True)))
        except Exception:
            pass

    def iniciar_automacao(self):
        if self.engine.is_running:
            return
        try:
            cfg = self._obter_config_atual()
        except Exception as exc:
            messagebox.showerror("Configuração Inválida", f"Verifique os valores numéricos informados:\n{exc}")
            return

        self.btn_iniciar.configure(state="disabled")
        self.btn_login.configure(state="disabled")
        self.btn_parar.configure(state="normal")
        self.progressbar["value"] = 0
        self.progressbar["maximum"] = cfg.quantidade_pesquisas

        t = threading.Thread(target=self._worker_fluxo, args=(cfg,), daemon=True)
        t.start()

    def _worker_fluxo(self, cfg: AutomationConfig):
        self.engine.executar_fluxo(cfg)
        self.after(0, self._restaurar_botoes)

    def abrir_login_manual(self):
        if self.engine.is_running:
            return
        cfg = self._obter_config_atual()
        self.btn_iniciar.configure(state="disabled")
        self.btn_login.configure(state="disabled")
        self.btn_parar.configure(state="normal")

        t = threading.Thread(target=self._worker_login, args=(cfg,), daemon=True)
        t.start()

    def _worker_login(self, cfg: AutomationConfig):
        self.engine.abrir_perfil_para_login(cfg)
        self.after(0, self._restaurar_botoes)

    def parar_automacao(self):
        if self.engine.is_running:
            self.engine.stop()

    def _restaurar_botoes(self):
        self.btn_iniciar.configure(state="normal")
        self.btn_login.configure(state="normal")
        self.btn_parar.configure(state="disabled")

    def _on_engine_report(self, report: ActionReport):
        self.after(0, self._adicionar_relatorio_ui, report)

    def _adicionar_relatorio_ui(self, report: ActionReport):
        self.all_reports.append(report)
        filtro = self.filtro_atual.get()
        if filtro == "TODOS" or report.status == filtro:
            item_id = self.tree.insert(
                "",
                0,
                values=(
                    report.horario,
                    report.acao,
                    report.etapa,
                    report.status,
                    f"{report.duracao_s:.1f}s",
                    report.motivo,
                ),
                tags=(report.status,),
            )
            if report.status == "ERRO":
                self.lbl_detalhe_erro.configure(
                    text=f"[{report.horario}] FALHA em '{report.acao}' ({report.etapa}): {report.motivo}",
                    fg="#DC2626",
                )
            self.tree.see(item_id)

    def _atualizar_tabela_filtrada(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        filtro = self.filtro_atual.get()
        for report in reversed(self.all_reports):
            if filtro == "TODOS" or report.status == filtro:
                self.tree.insert(
                    "",
                    "end",
                    values=(
                        report.horario,
                        report.acao,
                        report.etapa,
                        report.status,
                        f"{report.duracao_s:.1f}s",
                        report.motivo,
                    ),
                    tags=(report.status,),
                )

    def _ao_selecionar_linha(self, _event):
        selecao = self.tree.selection()
        if not selecao:
            return
        valores = self.tree.item(selecao[0], "values")
        if valores and len(valores) >= 6:
            horario, acao, etapa, status, duracao, motivo = valores
            cor = "#DC2626" if status == "ERRO" else ("#92400E" if status == "AVISO" else "#0F172A")
            self.lbl_detalhe_erro.configure(
                text=f"[{horario} | {status} | {duracao}] {acao} ({etapa}) → {motivo}",
                fg=cor,
            )

    def _on_engine_status(self, status_texto: str):
        self.after(0, self._atualizar_status_ui, status_texto)

    def _atualizar_status_ui(self, status_texto: str):
        self.lbl_kpi_status.configure(text=status_texto)
        if "Execução" in status_texto or "Pesquisando" in status_texto or "Permanecendo" in status_texto or "Aguardando" in status_texto:
            self.lbl_badge_status.configure(text="● EM EXECUÇÃO", bg="#16A34A")
        elif "Parando" in status_texto or "Cancelado" in status_texto:
            self.lbl_badge_status.configure(text="● CANCELADO", bg="#D97706")
        else:
            self.lbl_badge_status.configure(text=f"● {status_texto.upper()}", bg="#334155")

    def _on_engine_progress(self, pesquisas: int, meta: int, cards: int, erros: int):
        self.after(0, self._atualizar_progresso_ui, pesquisas, meta, cards, erros)

    def _atualizar_progresso_ui(self, pesquisas: int, meta: int, cards: int, erros: int):
        self.lbl_kpi_pesquisas.configure(text=f"{pesquisas} / {meta}")
        self.lbl_kpi_cards.configure(text=str(cards))
        self.lbl_kpi_erros.configure(text=str(erros))
        self.progressbar["maximum"] = max(1, meta)
        self.progressbar["value"] = pesquisas

    def limpar_relatorio(self):
        self.all_reports.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.lbl_detalhe_erro.configure(
            text="Relatório limpo. Clique em Iniciar para registrar novas atividades.",
            fg="#0F172A",
        )

    def exportar_csv(self):
        if not self.all_reports:
            messagebox.showinfo("Exportar Relatório", "Ainda não há registros na tabela para exportar.")
            return
        caminho = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("Arquivo CSV", "*.csv")],
            initialfile=f"relatorio_rewards_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        )
        if not caminho:
            return
        try:
            with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["Horario", "Acao", "Etapa", "Status", "Duracao_Segundos", "Motivo_Diagnostico"])
                for r in self.all_reports:
                    writer.writerow([r.horario, r.acao, r.etapa, r.status, r.duracao_s, r.motivo])
            messagebox.showinfo("Exportar Relatório", f"Relatório salvo com sucesso em:\n{caminho}")
        except Exception as exc:
            messagebox.showerror("Erro ao Exportar", f"Não foi possível salvar o arquivo CSV:\n{exc}")

    def _ao_fechar(self):
        if self.engine.is_running:
            self.engine.stop()
        self.destroy()


if __name__ == "__main__":
    app = RewardsDashboardApp()
    app.mainloop()

