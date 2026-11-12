# -*- coding: utf-8 -*-
"""
Gerador de termos de pesquisa naturais em português + Mapeador inteligente para as
Missões Específicas do Microsoft Rewards ("Explore no Bing" / "Pesquise para Ganhar").
"""

import random
from datetime import datetime

# Mapeamento de palavras-chave das missões do painel Rewards para pesquisas reais que ativam a missão
MAPA_MISSOES_ESPECIFICAS = [
    (["letra", "música", "musica", "canção", "lyrics", "som"], [
        "letra da musica evidencias chitaozinho e xororo",
        "letra da musica aquarela toquinho",
        "letra da musica tempo perdido legiao urbana",
    ]),
    (["clima", "tempo", "previsão", "temperatura", "chuva", "weather"], [
        "previsao do tempo sao paulo amanha",
        "clima hoje no rio de janeiro temperatura",
        "previsao do tempo para esta semana",
    ]),
    (["receita", "cozinha", "bolo", "prato", "comida", "ingredientes", "jantar"], [
        "receita de estrogonofe de frango simples",
        "receita de bolo de cenoura com calda de chocolate",
        "como fazer lasanha a bolonhesa receita facil",
    ]),
    (["voo", "passagem", "aérea", "viagem", "viajar", "destino", "turismo", "flight"], [
        "passagens aereas de sao paulo para salvador",
        "voos baratos para lisboa portugal",
        "melhores destinos de viagem no nordeste",
    ]),
    (["hotel", "hospedagem", "pousada", "estadia"], [
        "hoteis em gramado rio grande do sul",
        "pousadas em paraty perto do centro historico",
        "hoteis em fortaleza beira mar",
    ]),
    (["filme", "cinema", "elenco", "cartaz", "série", "serie", "movie"], [
        "filmes em cartaz no cinema esta semana",
        "elenco do filme auto da compadecida",
        "melhores filmes de ficcao cientifica",
    ]),
    (["tradu", "idioma", "inglês", "ingles", "dicionário", "significado", "translate"], [
        "traduzir bom dia como vai voce para ingles",
        "tradutor portugues para espanhol online",
        "significado da palavra resiliencia no dicionario",
    ]),
    (["moeda", "dólar", "dolar", "euro", "convers", "câmbio", "cambio", "cotação"], [
        "converter 100 dolares em reais hoje",
        "cotacao do euro hoje em reais",
        "conversor de moedas dolar para real",
    ]),
    (["ação", "ações", "bolsa", "ibovespa", "mercado", "finanças", "investimento", "stock"], [
        "cotacao acoes petrobras petr4 hoje",
        "indice ibovespa pontos hoje grafico",
        "cotacao vale3 bolsa de valores hoje",
    ]),
    (["compra", "loja", "preço", "oferta", "produto", "presente", "shopping"], [
        "preco fone de ouvido bluetooth com cancelamento de ruido",
        "comprar notebook gamer ofertas comparativo",
        "melhores smartphones custo beneficio",
    ]),
    (["restaurante", "comer", "almoço", "pizzaria", "cafeteria", "perto"], [
        "restaurantes italianos em sao paulo",
        "melhores pizzarias perto de mim",
        "cafeterias abertas agora na regiao",
    ]),
    (["esporte", "futebol", "jogo", "placar", "campeonato", "tabela", "brasileirão"], [
        "tabela do campeonato brasileiro serie a",
        "jogos de futebol hoje resultados ao vivo",
        "classificacao atualizada do brasileirao",
    ]),
    (["notícia", "noticia", "jornal", "atualidades", "manchete", "hoje"], [
        "principais noticias do brasil e do mundo hoje",
        "ultimas noticias de tecnologia e ciencia",
        "resumo das noticias de economia hoje",
    ]),
    (["mapa", "rota", "distância", "como chegar", "direção", "endereço"], [
        "distancia entre sao paulo e curitiba pelo mapa",
        "como chegar ao parque ibirapuera mapa",
        "mapa das rodovias do estado de sao paulo",
    ]),
    (["saúde", "sintoma", "exercício", "bem-estar", "vitamina", "treino"], [
        "beneficios da caminhada diaria para a saude",
        "alimentos ricos em vitamina c e ferro",
        "exercicios de alongamento para coluna",
    ]),
]

# Lista principal combinando todas as categorias de missões + temas gerais
TEMAS_BASE = [
    # Pesquisas que ativam missões temáticas ("Explore no Bing")
    "previsao do tempo para esta semana na minha cidade",
    "letra da musica aquarela toquinho completa",
    "receita de bolo de cenoura com cobertura de chocolate",
    "passagens aereas de sao paulo para recife",
    "hoteis em florianopolis perto da praia",
    "filmes em cartaz no cinema esta semana",
    "traduzir bom dia tudo bem para ingles",
    "converter 50 dolares para reais hoje",
    "cotacao das acoes petr4 e vale3 hoje",
    "tabela do campeonato brasileiro serie a atualizada",
    "restaurantes e pizzarias abertos hoje",
    "principais noticias de tecnologia hoje",
    "preco monitor 27 polegadas ips comparativo",
    "distancia entre rio de janeiro e belo horizonte",
    # Pesquisas gerais variadas
    "como funciona a inteligencia artificial generativa",
    "historia da computacao e primeiros computadores",
    "melhores destinos de viagem na america do sul",
    "dicas de produtividade no trabalho remoto",
    "beneficios da caminhada diaria para a saude",
    "como plantar temperos em apartamento pequeno",
    "principais atalhos do windows 11 no teclado",
    "curiosidades sobre o sistema solar e planetas",
    "como organizar financas pessoais em planilha",
    "historia do cafe no brasil e regioes produtoras",
    "o que e computacao em nuvem e como funciona",
    "exercicios de alongamento para quem trabalha sentado",
    "livros classicos da literatura brasileira para ler",
    "como economizar bateria do notebook no dia a dia",
    "receita de pao caseiro facil e rapido",
    "principais parques nacionais do brasil para visitar",
    "como aprender programacao python do zero",
    "diferenca entre renda fixa e renda variavel",
    "historia das olimpiadas modernas e modalidades",
    "dicas para melhorar a qualidade do sono a noite",
    "como limpar tela de monitor sem danificar",
    "principais museus de historia e ciencia no mundo",
    "receita de lasanha a bolonhesa tradicional",
    "o que sao energias renovaveis solar e eolica",
    "como funciona o cambio automatico nos carros",
    "curiosidades sobre a floresta amazonica e biodiversidade",
    "dicas de fotografia com celular para iniciantes",
    "historia da musica popular brasileira mpb",
    "como fazer arroz soltinho passo a passo",
    "principais linguagens de programacao mais usadas",
]

COMPLEMENTOS = [
    "",
    " guia completo",
    " passo a passo",
    " dicas praticas",
    " resumo",
    f" {datetime.now().year}",
]


def obter_pesquisa_para_missao(titulo_card: str) -> str:
    """
    Dado o título/descrição de um card de missão do Microsoft Rewards,
    retorna uma frase de pesquisa específica daquele tema para pontuar a missão.
    """
    txt = (titulo_card or "").lower()
    for palavras_chave, opcoes in MAPA_MISSOES_ESPECIFICAS:
        for kw in palavras_chave:
            if kw in txt:
                return random.choice(opcoes)

    # Se o título do card não bater com uma categoria conhecida, limpa o próprio título
    # ou usa uma pesquisa natural relacionada
    limpo = "".join(ch for ch in txt if ch.isalnum() or ch == " ").strip()
    palavras = [p for p in limpo.split() if len(p) > 2 and p not in ("pontos", "ganhe", "bing", "pesquise", "clique", "mais", "para")]
    if len(palavras) >= 2:
        return " ".join(palavras[:6])
    return random.choice(TEMAS_BASE[:14])


def gerar_lista_pesquisas(quantidade: int = 30) -> list[str]:
    """
    Gera a lista de termos garantindo que as primeiras pesquisas cubram as missões temáticas
    do Microsoft Rewards (clima, letras, receitas, voos, filmes, tradução, moedas, etc.).
    """
    missoes_prioritarias = TEMAS_BASE[:14].copy()
    random.shuffle(missoes_prioritarias)

    gerais = TEMAS_BASE[14:].copy()
    random.shuffle(gerais)

    pool = missoes_prioritarias + gerais
    resultado = []

    idx = 0
    while len(resultado) < quantidade:
        base = pool[idx % len(pool)]
        if idx >= len(pool):
            comp = random.choice([c for c in COMPLEMENTOS if c])
            termo = f"{base}{comp}"
        else:
            termo = base

        if termo not in resultado:
            resultado.append(termo)
        idx += 1

    return resultado
