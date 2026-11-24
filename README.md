# Painel DJEN

Painel pessoal e privado com as comunicações do Diário de Justiça Eletrônico Nacional (DJEN/CNJ) da OAB 350073/SP, atualizado a cada hora.

## Como funciona

- `djen_painel.py` consulta a API pública do DJEN (`comunicaapi.pje.jus.br`) pelas OABs de `config.json`, guarda o histórico em `dados/` sem duplicar e gera `painel.html`.
- A primeira execução busca os últimos 30 dias. As seguintes buscam os últimos 3 dias, com sobreposição para não perder nada.
- Se a coleta falhar, o painel mostra o erro e mantém o histórico já salvo.
- `dados/` e `painel.html` ficam fora do Git, porque contêm dados de processos e clientes.

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

Em `config.json`, inclua outras OABs na lista `oabs` (por exemplo, colegas do escritório) e ajuste `dias_carga_inicial`.

## Observações

- Publicação e início de prazo exibidos são **estimativas** (Lei 11.419/2006, art. 4º, §§ 3º e 4º; CPC, art. 224). Consideram só feriados nacionais e os pontos facultativos forenses móveis. Conferir sempre no sistema do tribunal.
- A marcação "tratada" fica salva no navegador em que o painel é aberto.
- Log de execução: `dados/coletor.log`.
