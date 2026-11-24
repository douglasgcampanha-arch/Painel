# Painel DJEN

Painel pessoal e privado, atualizado a cada hora, com duas abas:

- **Intimações**: comunicações do Diário de Justiça Eletrônico Nacional (DJEN/CNJ) da OAB 350073/SP.
- **Movimentações**: andamentos dos processos da carteira pela API Pública do DataJud (CNJ), que reúne os dados de todos os tribunais e sistemas (PJe, eproc, e-SAJ, Projudi etc.).
- **eproc TJSP**: citações e intimações em aberto no Painel do Advogado do eproc TJSP, lidas com o certificado digital A1, somente para leitura.

## Instalação no Mac (recomendada)

1. Instale o Python 3 (python.org).
2. Coloque esta pasta em `~/PainelDJEN`. Não use Documentos, Mesa, Downloads nem iCloud, porque o macOS bloqueia tarefas automáticas nessas pastas.
3. No Terminal: `cd ~/PainelDJEN && bash instalar_mac.command`. O instalador:
   - cria o ambiente Python e instala o navegador do robô;
   - copia o certificado .pfx para `certificado/` (fora do Git) e guarda a senha nas Chaves do macOS;
   - agenda a coleta a cada 1 hora (launchd `br.painel-djen.coletor`);
   - abre o primeiro acesso ao eproc para validar o 2FA.
4. Deixe o Mac sem repouso automático (Ajustes do Sistema > Bateria/Energia).

Para baixar a versão mais recente do código: `bash atualizar_codigo.command` (requer `gh auth login` uma vez).

Arquivos de apoio: `atualizar_agora.command`, `eproc_primeiro_acesso.command` (revalidar o 2FA), `eproc_diagnostico.command` (estrutura das telas para ajuste, sem dados de processos) e `desinstalar_mac.command`.

## eproc TJSP (certificado digital)

- O login usa o certificado A1 na conexão com `certificado-sso.tjsp.jus.br`, sem PJeOffice. O 2FA obrigatório é validado uma vez com "Não usar o 2FA neste dispositivo e navegador". O perfil do navegador do robô fica em `dados/perfil_eproc`.
- Quando o eproc voltar a pedir o código, a coleta do eproc pausa, o Mac mostra uma notificação e o painel exibe um aviso. Basta rodar `eproc_primeiro_acesso.command`.
- O robô lê a seção "Citações/Intimações" (abas SP, TJSP e EF) e as listas de cada categoria. Ele **nunca** aciona "Abrir Prazo" nem abre atos: há trava pelo texto do botão e bloqueio de requisições de abertura de prazo ou ciência.
- Leitura a cada 2 horas, das 7h às 21h, configurável em `eproc_tjsp` no `config.json`.
- Se o .pfx usar criptografia antiga e o navegador recusar, converta para PEM e preencha `certificado_pem` e `chave_pem`.
- A senha do certificado fica só nas Chaves do macOS (serviço `painel-eproc-certificado`), nunca em arquivo.

## Como funciona

- `djen_painel.py` consulta a API pública do DJEN (`comunicaapi.pje.jus.br`) pelas OABs de `config.json`, guarda o histórico em `dados/` sem duplicar e gera `painel.html`.
- Busca e mantém somente as comunicações dos últimos 7 dias (`janela_dias` no `config.json`). A carteira do DataJud acompanha só os processos com intimação nesse período, mais os incluídos manualmente.
- Se a coleta falhar, o painel mostra o erro e mantém o histórico já salvo.
- `dados/` e `painel.html` ficam fora do Git, porque contêm dados de processos e clientes.

## Integração com o Astrea (Aurum)

O Astrea não tem API pública. Por isso, um robô no navegador, logado com a sua conta, lança no Astrea as tarefas e prazos que você confirmar no painel.

- **Botão "Enviar ao Astrea"** na análise de cada publicação do DJEN e em cada intimação do eproc. Ele abre uma janela já preenchida (tipo, data, título e descrição com a orientação), que você confere e edita antes de enviar.
- A **data sugerida** é o prazo fatal estimado:
  - DJEN: início estimado mais o prazo da análise, em dias úteis, pulando fins de semana, feriados nacionais e o recesso de 20/12 a 20/01 (CPC, art. 220);
  - eproc: o Final Prazo do próprio sistema.
- O painel passa a ser aberto em `http://127.0.0.1:8765`, um servidor local que só responde no próprio Mac e é protegido por um código secreto. Aberto como arquivo, o painel continua funcionando, mas não envia ao Astrea.
- Configuração: `bash configurar_astrea.command` ativa o servidor, faz o login do robô no Astrea e grava o diagnóstico das telas (`dados/astrea_diagnostico/estrutura.json`, sem dados de processos) para calibrar o preenchimento.
- Fila e histórico ficam em `dados/astrea_fila.json`, e o log em `dados/coletor.log`.

## Análise das publicações com IA

Cada publicação do DJEN ganha o botão **Análise**, gerado pelo Claude (API da Anthropic). A análise indica:

- se o ato é dirigido ao seu cliente (e qual parte/polo);
- se exige manifestação, a providência e o prazo;
- orientação, checklist para deixar preparado, estrutura da peça e pontos de atenção.

Há também os filtros "Exigem manifestação" e "Dirigidas ao meu cliente", e o botão "Copiar análise".

- Para ativar, rode `bash configurar_analise_ia.command`. Ele usa o **Claude Code com a sua assinatura do Claude, sem chave de API**:
  - instala o Claude Code se faltar;
  - faz o login, testa e pergunta os nomes dos clientes.
- A análise é feita pelo coletor, até 10 publicações novas por execução, sem ferramentas e numa pasta isolada. O resultado fica em `dados/analises.json`.
- Consome o limite de uso da assinatura. Quando o limite acaba, a análise para e continua na próxima hora.
- Se o agendamento não conseguir usar o login, gere um token com `claude setup-token` e guarde nas Chaves do macOS com o serviço `painel-claude-oauth`.
- Opcional: `"motor": "api"` usa a API da Anthropic com chave (serviço `painel-anthropic-api`), cobrada à parte.
- O teor das publicações é enviado ao Claude para análise.
- A análise é um apoio: conferir sempre o teor e os autos antes de agir.

## DataJud (movimentações em todos os sistemas)

- A carteira é montada sozinha: todo processo que aparece numa intimação do DJEN passa a ser acompanhado. Para incluir outros processos, liste os números em `"processos"` no `config.json`.
- O tribunal é identificado pelo número CNJ (segmento J.TR). Isso cobre TJs, TRFs, TRTs, TREs, TJMs, STJ, TST, TSE e STM. O STF não está na API pública.
- Cada processo é consultado no máximo a cada `datajud_intervalo_horas` (padrão 6 h), com até `datajud_max_por_execucao` processos por execução (padrão 40). Isso evita sobrecarregar a API.
- Na primeira consulta de cada processo, o histórico entra como base. Nas seguintes, só o que for acrescentado aparece como "nova".
- Limites da fonte: os tribunais enviam os dados em lotes, com defasagem de horas a dias. Processos sigilosos não aparecem, e não há teor de decisões nem nomes de partes.
- Chave pública: o CNJ divulga e pode trocar a chave em datajud-wiki.cnj.jus.br/api-publica/acesso. Se a consulta passar a retornar erro 401/403, cole a nova chave em `"datajud_chave"`.
- Uso sujeito ao Termo de Uso da API Pública do DataJud (finalidade legal e não comercial).

## Requisito importante

A API do DJEN **bloqueia acessos de fora do Brasil**: o CloudFront recusa a conexão com 403 por país. Por isso o coletor precisa rodar numa máquina com internet brasileira, como o computador do escritório ou uma VPS no Brasil. Serviços em nuvem estrangeiros, como o GitHub Actions, não funcionam.

## Instalação (Windows, só DJEN e DataJud)

1. Instale o Python 3.9 ou superior (python.org), marcando "Add python.exe to PATH".
2. Baixe esta pasta para o computador. O caminho não deve ter acentos.
3. Dê dois cliques em `agendar_windows.bat`. Ele faz a primeira coleta, cria a tarefa horária "Painel DJEN" e abre o painel.
4. Para atualizar na hora, use `atualizar_agora.bat`.
5. Para remover o agendamento: `schtasks /delete /tn "Painel DJEN" /f`.

Linux/macOS: `crontab -e` e adicione `0 * * * * python3 /caminho/djen_painel.py`.

## Configuração

O `config.json` é local (fica fora do Git e é criado a partir de `config.exemplo.json`; chaves novas entram sozinhas). Nele, inclua outras OABs na lista `oabs` (por exemplo, colegas do escritório), processos avulsos em `processos`, e ajuste `janela_dias` e os parâmetros `datajud_*`. Para desligar o DataJud, use `"datajud_ativo": false`.

## Observações

- Publicação e início de prazo exibidos são **estimativas** (Lei 11.419/2006, art. 4º, §§ 3º e 4º; CPC, art. 224). Consideram só feriados nacionais e os pontos facultativos forenses móveis. Conferir sempre no sistema do tribunal.
- A marcação "tratada" fica salva no navegador em que o painel é aberto.
- Log de execução: `dados/coletor.log`.
