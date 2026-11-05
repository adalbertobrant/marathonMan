# 🔐 Política de privacidade e tratamento de dados

**Aplicação:** Maratona de Melancias 🍉
**Controlador:** equipe de organização da Maratona
**Base legal:** consentimento (LGPD, Lei 13.709/2018, art. 7º, I) para navegação;
execução de contrato/legítimo interesse apenas para a operação da escala.
**Última atualização:** 04/11/2026

---

## 1. Princípio geral

O app só mede navegação **depois** de a pessoa clicar em "Pode registrar".
Sem esse clique, ele funciona igual e **não grava nada**. Não existe rastreamento
oculto, nem pixel escondido sem aviso, nem gravação de tela.

---

## 2. Inventário de dados

| Dado | Onde fica | Finalidade | Retenção |
| --- | --- | --- | --- |
| Id de sessão aleatório (32 hex) | cookie `melancias_sid` + SQLite | não repetir o funil a cada refresh | cookie 30 dias · log 90 dias |
| Tela aberta e ordem das telas | SQLite (`events.screen`) | achar onde a orientação trava | 90 dias |
| Tempo aproximado por tela | SQLite (`events.ts` de `view`/`leave`) | detectar página confusa | 90 dias |
| Nome escolhido na lista | SQLite (`events.person`) | entregar o resumo certo | 90 dias |
| Código do país (2 letras) | SQLite (`events.country`) | aplicar a regra "só Brasil" | 90 dias |
| Contagem de fotos/palavras | SQLite (`events.meta`) | saber se a meditação é usada | 90 dias |
| Foto enviada na meditação | **só memória do navegador** | exibição imediata | até fechar a aba |
| Palavras positivas | **só memória do navegador** | mural da sessão | até fechar a aba |
| Check-in emocional | **só memória do navegador** | acolhimento no momento | até fechar a aba |

### O que **nunca** é coletado

- endereço IP (nem em log de servidor do app);
- geolocalização precisa, operadora, MAC, IMEI;
- conteúdo de fotos, palavras ou check-in;
- gravação de tela, vídeo, áudio ou teclas;
- senhas, dados de saúde, CPF, e-mail (o app não pede nada disso);
- dados de menores — o público é universitário.

---

## 3. Cookie e pixel

**Cookie `melancias_sid`**
- first-party, `SameSite=Lax`, `path=/`, expira em 30 dias (configurável);
- contém apenas um id aleatório de 128 bits — nenhum dado pessoal;
- existe para manter a sessão entre refreshs e evitar contar a mesma pessoa
  várias vezes;
- só é gravado **após o consentimento**. Sem consentimento, a sessão vive apenas
  na memória da aba.

**Pixel 1×1 (`ANALYTICS_PIXEL_URL`)**
- é um `<img>` de 1×1 px, invisível na página;
- **desligado por padrão**: sem a variável configurada, não existe;
- quando configurado, o endereço aparece na tela **Privacidade** e só dispara
  depois do consentimento;
- envia: id anônimo da sessão, tela e horário. Não envia nome, IP (o servidor do
  pixel vê a conexão, então escolha um endpoint próprio) nem conteúdo.

> Por que não um pixel "escondido de verdade"? Porque rastrear pessoas sem
> aviso viola a LGPD e a confiança de quem está doando o fim de semana. O pixel
> existe, é funcional, mas é declarado.

---

## 4. Acesso restrito ao Brasil

- A decisão usa o **código do país** informado pelo CDN
  (`CF-IPCountry`, `X-Vercel-IP-Country`, etc.) ou, opcionalmente, um lookup
  por IP configurado pela organização.
- Se o país não for identificável, vale `UNKNOWN_COUNTRY_POLICY`
  (padrão: **liberar**, para não travar ninguém por engano).
- Saídas de rede Tor (`T1`) são bloqueadas.
- Com `ENABLE_IP_INTEL=1`, uma consulta opcional a um serviço externo verifica
  se o IP é proxy/hosting. É **best-effort**: VPNs residenciais podem passar e
  redes legítimas podem ser barradas.
- **Nenhum IP é armazenado**: só o código do país e o motivo do bloqueio.

Limitação honesta: não existe forma 100% confiável de detectar VPN apenas por
IP. O bloqueio reduz acesso indevido, não elimina.

---

## 5. Direitos da pessoa (LGPD art. 18)

Na tela **Privacidade**, em um clique:

- **confirmação e acesso** — a política mostra exatamente o que é medido;
- **revogação do consentimento** — interrompe a coleta imediatamente;
- **eliminação** — apaga todos os eventos daquela sessão (`DELETE FROM events WHERE sid = ?`);
- **informação** — retenção, finalidade e ausência de compartilhamento.

Pedidos adicionais (correção, portabilidade, informação sobre compartilhamento)
podem ser feitos diretamente ao núcleo da organização.

---

## 6. Segurança

- banco SQLite local com WAL; sem exposição de porta;
- painel da organização protegido por senha (`ADMIN_PASSWORD`) comparada com
  `hmac.compare_digest` (tempo constante);
- nenhum segredo no código: tudo por variável de ambiente/secrets;
- fotos processadas em memória, com remoção de EXIF/GPS e limite de tamanho;
- retenção automática a cada início de sessão (`RETENTION_DAYS`, padrão 90);
- dependências mínimas (Streamlit + pandas) para reduzir superfície.

---

## 7. Compartilhamento

Não há compartilhamento com terceiros por padrão. Se a organização configurar:

- `ANALYTICS_PIXEL_URL` → o endpoint escolhido recebe id anônimo + tela + horário;
- `GEO_LOOKUP_URL` / `IP_INTEL_URL` → o serviço escolhido recebe o IP no momento
  da consulta (não é armazenado pelo app);
- `SHEET_CSV_URL` → o Google Sheets é lido (somente leitura).

Cada uma dessas variáveis é uma decisão da organização e deve constar no aviso
aos participantes.

---

## 8. Encarregado e contato

Encarregado(a) pelo tratamento de dados: equipe de organização da Maratona.
Canal para exercer direitos: o mesmo canal de comunicação usado com as melancias
(WhatsApp/Discord do evento) ou e-mail da coordenação.

---

## 9. Mudanças nesta política

Alteração de coleta, finalidade ou prazo exige atualização deste documento, da
tela **Privacidade** e novo consentimento quando a base legal for consentimento.
