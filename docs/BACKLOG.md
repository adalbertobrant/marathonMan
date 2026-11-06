# 📋 Backlog, critérios de aceite e sprints

Produto: **Maratona de Melancias 🍉** — painel de organização e cuidado.
Time: 1 pessoa de produto/dev + revisão da organização.
Cadência: sprints de 1 dia (maratona é curta), revisão a cada entrega, `make check` obrigatório.

---

## 1. Personas

| Persona | Dor | Sucesso |
| --- | --- | --- |
| **Melancia** (voluntárie, 20–25 anos, universidade) | "não sei onde estou na escala", "são 8 abas" | abre o app, se identifica e vê a própria escala em < 30 s |
| **Núcleo / organizador** | "não sei quem vai faltar nem onde o pessoal se perde" | vê funil, abandonos e escala de todo mundo numa tela |
| **Coordenação** | "preciso reconhecer quem segurou a maratona" | pódio de horas + parabéns em destaque |

---

## 2. Épicos

| # | Épico | Valor | Status |
| --- | --- | --- | --- |
| E1 | Escala individual sem abas | reduz tempo e ansiedade | ✅ |
| E2 | Mural de tarefas de todo mundo | coordenação e transparência | ✅ |
| E3 | Destaques e reconhecimento | pertencimento | ✅ |
| E4 | Meditação e cuidado | saúde mental no evento | ✅ |
| E5 | Log de navegação e funil | melhoria contínua do onboarding | ✅ |
| E6 | Acesso restrito ao Brasil | regra do evento | ✅ |
| E7 | Privacidade e consentimento | LGPD e confiança | ✅ |
| E8 | Robustez e testes | "não pode quebrar" | ✅ |

---

## 3. Histórias de usuário

Formato: **Como** … **quero** … **para** … + critérios de aceite (Dado/Quando/Então).

### E1 — Escala individual

**H1.1 Identificação** · 3 pts · ✅
Como melancia, quero me achar pelo nome para ver só o que é meu.
- **Dado** que digito "leticia" (sem acento, minúsculo), **quando** busco, **então** vejo "Letícia Moura Lemos".
- **Dado** que não há resultado, **então** vejo um aviso gentil e o convite de falar com o núcleo.
- **Dado** que escolhi meu nome, **então** ele fica na sessão e aparece na sidebar.

**H1.2 Resumo** · 5 pts · ✅
Como melancia, quero horas, funções, lista e reunião juntas.
- **Dado** meu nome, **então** vejo horas, funções, lista, reunião e a próxima tarefa.
- **Dado** que a tarefa virou madrugada (23:30→01:00), **então** a duração é 1h30, não negativa.
- **Dado** que marco "feito", **então** a barra de progresso sobe e a marcação persiste na sessão.

**H1.3 "Tô pronto"** · 2 pts · ✅
- **Dado** que clico em "Tô pronto(a) pro dia", **então** vejo confete, mensagem de cuidado e a etapa `pronto` é registrada.

### E2 — Mural de tarefas

**H2.1 Filtros** · 3 pts · ✅
- **Dado** o filtro "Sábado", **então** só aparecem atividades de sábado.
- **Dado** busca por "parque", **então** aparecem atividades/locais com esse termo (sem acento).
- **Dado** que filtro, **então** posso baixar exatamente essa visão em CSV.

**H2.2 Só as minhas** · 2 pts · ✅
- **Dado** que me identifiquei, **então** existe um bloco recolhido com só as minhas atividades.

### E3 — Destaques

**H3.1 Pódio** · 3 pts · ✅
- **Dado** o ranking, **então** as 3 maiores horas aparecem com 🥇🥈🥉 e mensagem de parabéns.
- **Dado** empate de horas, **então** desempata por funções e depois por nome (ordem estável).

**H3.2 Todas as melancias** · 2 pts · ✅
- **Dado** a lista completa, **então** cada pessoa tem badges de lista, horas, funções e reunião.

### E4 — Meditação

**H4.1 Palavras positivas** · 3 pts · ✅
- **Dado** que escrevo uma palavra, **então** ela aparece no mural **da sessão**.
- **Dado** que fecho a aba, **então** as palavras somem (nada em disco).

**H4.2 Fotos efêmeras** · 5 pts · ✅
- **Dado** que envio uma foto, **então** ela aparece só para mim e os metadados EXIF/GPS são removidos.
- **Dado** que recarrego/fecho, **então** não há arquivo de imagem em disco.
- **Dado** arquivo > 8 MB, **então** recebo erro claro e nada é exibido.

**H4.3 Check-in emocional** · 2 pts · ✅
- **Dado** que escolho "no limite", **então** recebo acolhimento e convite a falar com o núcleo.

### E5 — Log e funil

**H5.1 Consentimento** · 5 pts · ✅
- **Dado** a primeira visita, **então** vejo banner com o que é medido e duas opções.
- **Dado** que recuso, **então** nenhum evento é gravado e o app funciona igual.
- **Dado** que aceito, **então** os eventos começam a ser gravados naquele instante (inclusive a tela atual).

**H5.2 Trilha e caminho correto** · 5 pts · ✅
- **Dado** que abro as telas na ordem canônica, **então** a sessão conta como `completo`.
- **Dado** que pulo "Quem é você?", **então** o painel mostra `primeira_falha = quem`.
- **Dado** que volto para uma tela anterior, **então** a sessão é marcada `fora_de_ordem`.

**H5.3 Painel da organização** · 5 pts · ✅
- **Dado** que não há `ADMIN_PASSWORD`, **então** o painel não aparece na navegação.
- **Dado** senha errada, **então** erro e nenhuma métrica.
- **Dado** senha certa, **então** vejo sessões, completude, abandonos, bloqueios e CSV.

### E6 — Acesso ao Brasil

**H6.1 Bloqueio por país** · 5 pts · ✅
- **Dado** cabeçalho `cf-ipcountry: US`, **então** vejo "Acesso restrito" e nenhuma navegação.
- **Dado** `cf-ipcountry: BR`, **então** acesso liberado.
- **Dado** país desconhecido, **então** vale `UNKNOWN_COUNTRY_POLICY` (padrão: liberar).
- **Dado** bloqueio, **então** o IP **não** é gravado — só o código do país.

**H6.2 Reputação de IP (opcional)** · 3 pts · ✅
- **Dado** `ENABLE_IP_INTEL=1` e IP marcado como proxy/hosting, **então** acesso bloqueado com motivo.
- **Dado** API fora do ar, **então** decisão anterior é mantida (fail-open) e nada quebra.

### E7 — Privacidade

**H7.1 Transparência** · 3 pts · ✅
- **Dado** a tela Privacidade, **então** vejo tabela do que é coletado, prazo e o que **nunca** é coletado.

**H7.2 Direito de exclusão** · 3 pts · ✅
- **Dado** que clico em revogar, **então** meus eventos são apagados e o registro para.

**H7.3 Pixel declarado** · 2 pts · ✅
- **Dado** `ANALYTICS_PIXEL_URL` configurado, **então** a política mostra a URL e o pixel só dispara com consentimento.

### E8 — Robustez

**H8.1 Nunca tela branca** · 5 pts · ✅
- **Dado** erro numa tela, **então** vejo mensagem amigável + detalhes técnicos recolhidos + botão para o início.
- **Dado** CSV da planilha inválido, **então** o app usa o snapshot embutido.
- **Dado** disco sem permissão, **então** o log cai para memória e o app avisa.

**H8.2 Suíte automatizada** · 5 pts · ✅
- **Dado** `make check`, **então** lint + 233 testes passam.
- **Dado** qualquer página, **então** existe teste de integração que a renderiza.

---

## 4. Definition of Done

Uma história só fecha quando:

1. critério de aceite escrito em Dado/Quando/Então;
2. teste automatizado cobrindo o caminho feliz **e** um caminho de erro;
3. `make check` verde (ruff + pytest);
4. nenhuma coleta nova sem atualização da tela **Privacidade** e de `docs/PRIVACIDADE.md`;
5. texto revisado em pt-BR, tom acolhedor, sem jargão;
6. funciona com dataset vazio e com banco indisponível.

---

## 5. Sprints

| Sprint | Foco | Entregas | Testes |
| --- | --- | --- | --- |
| S1 | Fundação | parser do dataset, normalização, horários, ranking | 42 |
| S2 | Escala individual | identificação, resumo, timeline, "tô pronto" | +14 |
| S3 | Mural e destaques | filtros, CSV, pódio, superlativos | +4 |
| S4 | Cuidado | meditação, fotos efêmeras, check-in, palavras | +23 |
| S5 | Log e funil | store SQLite, consentimento, trilha, painel | +30 |
| S6 | Acesso e privacidade | geo, VPN opcional, política, exclusão | +44 |
| S7 | Endurecimento | CI, docs, dataset vazio, concorrência, revisão | +26 |
| S8 | Programação oficial | grade da Final SBC 2026, filtro por dia, "acontecendo agora", .ics e surpresa de 14/11 | +49 |

**Total: 233 testes · 89% de cobertura do `app.py`.**

---

## 6. Riscos e mitigação

| Risco | Prob. | Impacto | Mitigação |
| --- | --- | --- | --- |
| Planilha muda de formato | média | alto | `normalize_dataset` + fallback para snapshot |
| Deploy efêmero perde o log | alta | médio | aviso na tela + runbook para volume/Postgres |
| Bloqueio por país erra (VPN/CGNAT) | média | alto | política `allow` para desconhecido + botão "tentar de novo" + contato |
| Alguém se incomoda com o log | média | alto | consentimento, exclusão em 1 clique, retenção 90 dias |
| Muitos acessos simultâneos no SQLite | baixa | médio | WAL + lock + fallback memória; caminho para Postgres |
| Upload de imagem grande | média | baixo | limite 8 MB + re-encode + thumbnail 1600 px |
| Foto com GPS vazando | baixa | alto | `sanitize_image` remove EXIF (testado) |

---

## 7. Métricas de sucesso

- **% de sessões com caminho completo** (meta: > 60%).
- **Tela de maior abandono** (ação: melhorar texto/atalho).
- **Tempo até ver o resumo** (meta: < 60 s).
- **Taxa de consentimento** (meta: > 80%).
- **Bloqueios por país desconhecido** (se subir, revisar `GEO_LOOKUP_URL`).

---

## 8. Próximos passos (backlog aberto)

- [ ] Trocar SQLite por Postgres/Turso para log persistente no Cloud.
- [ ] Notificação no WhatsApp/Discord 30 min antes da tarefa.
- [ ] Exportar "espelho de horas" para o financeiro.
- [ ] Modo offline/PWA para o dia do evento (rede do hotel).
- [ ] Traduzir microtextos para linguagem neutra revisada pela comunidade.
- [ ] Painel de NPS pós-evento (1 pergunta, anônima).
