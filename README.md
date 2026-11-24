# Painel DJEN

Painel pessoal e privado, atualizado a cada hora, com duas abas:

- **Intimações**: comunicações do Diário de Justiça Eletrônico Nacional (DJEN/CNJ) da OAB 350073/SP.
- **Movimentações**: andamentos dos processos da carteira pela API Pública do DataJud (CNJ), que reúne os dados de todos os tribunais e sistemas (PJe, eproc, e-SAJ, Projudi etc.).

## Como funciona

- `djen_painel.py` consulta a API pública do DJEN (`comunicaapi.pje.jus.br`) pelas OABs de `config.json`, guarda o histórico em `dados/` sem duplicar e gera `painel.html`.
- A primeira execução busca os últimos 30 dias. As seguintes buscam os últimos 3 dias, com sobreposição para não perder nada.
- Se a coleta falhar, o painel mostra o erro e mantém o histórico já salvo.
- `dados/` e `painel.html` ficam fora do Git, porque contêm dados de processos e clientes.

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

## Instalação (Windows)

1. Instale o Python 3.9 ou superior (python.org), marcando "Add python.exe to PATH".
2. Baixe esta pasta para o computador. O caminho não deve ter acentos.
3. Dê dois cliques em `agendar_windows.bat`. Ele faz a primeira coleta, cria a tarefa horária "Painel DJEN" e abre o painel.
4. Para atualizar na hora, use `atualizar_agora.bat`.
5. Para remover o agendamento: `schtasks /delete /tn "Painel DJEN" /f`.

Linux/macOS: `crontab -e` e adicione `0 * * * * python3 /caminho/djen_painel.py`.

## Configuração

Em `config.json`, inclua outras OABs na lista `oabs` (por exemplo, colegas do escritório), processos avulsos em `processos`, e ajuste `dias_carga_inicial` e os parâmetros `datajud_*`. Para desligar o DataJud, use `"datajud_ativo": false`.

## Observações

- Publicação e início de prazo exibidos são **estimativas** (Lei 11.419/2006, art. 4º, §§ 3º e 4º; CPC, art. 224). Consideram só feriados nacionais e os pontos facultativos forenses móveis. Conferir sempre no sistema do tribunal.
- A marcação "tratada" fica salva no navegador em que o painel é aberto.
- Log de execução: `dados/coletor.log`.
