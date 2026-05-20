# Sistema de Conciliação Financeira Inteligente

Projeto reutilizável para comparar extratos bancários com razão contábil/financeiro, encontrar pendências e gerar relatórios de auditoria.

## O que o sistema faz

- Importa CSV, XLSX, PDF, OFX e TXT.
- Padroniza datas, valores, históricos, fornecedores e tipos de movimento.
- Remove acentos, caracteres especiais e palavras irrelevantes como LTDA, ME, EIRELI, PAGAMENTO, PIX e TED.
- Compara extrato e razão obrigatoriamente por data exata e valor exato; fornecedor e histórico não interferem no match.
- Detecta meses diferentes entre os arquivos e concilia somente os meses em comum.
- Usa fuzzy matching com RapidFuzz quando instalado e fallback com `difflib`.
- Usa PyMuPDF para acelerar a leitura de PDFs grandes, com fallback para `pypdf`.
- Classifica cada achado como alta, média ou baixa confiança.
- Mostra entradas e saídas separadamente na interface.
- Gera Excel com resumo, entradas, saídas, pendências, matches, duplicidades, escopo de período e bases normalizadas.
- Disponibiliza botão `Exportar XLSX` ao final da conciliação.
- Pode usar histórico de equivalências em SQLite para melhorar conciliações futuras.

## Arquitetura

```text
financial_reconciliation/
  config.py                 Parâmetros do motor e thresholds
  models.py                 Modelo canônico de transações
  normalization.py          Limpeza textual, acentos, stopwords e tokens
  fuzzy.py                  Similaridade textual com RapidFuzz/fallback
  matching.py               Motor de conciliação e classificação
  database.py               SQLite para análises e histórico de equivalências
  reports.py                Exportação Excel
  cli.py                    Execução por linha de comando
  parsers/
    csv_parser.py           CSV/TSV bancário
    excel_parser.py         XLSX/XLS
    pdf_ledger_parser.py    Razão em PDF por extração de texto
    ofx_parser.py           OFX com biblioteca opcional ou regex
    txt_parser.py           TXT delimitado ou linhas de extrato
    universal.py            Roteador por extensão
app.py                      Dashboard Streamlit
```

## Algoritmo de matching

1. Carrega todos os arquivos para um modelo único: data, valor, direção, histórico, fornecedor, conta, origem e linha.
2. Normaliza texto removendo acentos, pontuação, termos societários e termos bancários irrelevantes.
3. Verifica os meses de cada arquivo e restringe a análise aos meses que existem no extrato e no razão.
4. Para cada lançamento do extrato, busca candidatos no razão somente quando data e valor são iguais.
5. Calcula score ponderado:
   - Valor: 34%
   - Data: 24%
   - Similaridade textual: 32%
   - Tipo/direção do movimento: 10%
   - Bônus de equivalência aprendida no SQLite quando houver alias confirmado em análises anteriores
6. Faz seleção um-para-um pelo maior score.
7. Se data e valor batem, o item fica como `Conciliado`, mesmo que fornecedor ou histórico estejam diferentes.
8. Classifica o resultado:
   - `Conciliado`
   - `Não encontrado no razão`
   - `Não encontrado no extrato`
   - `Divergência de valor`
   - `Divergência de data`
   - `Possível duplicidade`
   - `Correspondência parcial`

## Uso via interface

```powershell
streamlit run app.py
```

Depois, abra `http://localhost:8501`.

## Publicação online

Opção recomendada: GitHub privado + Streamlit Community Cloud.

1. Crie um repositório privado no GitHub.
2. Suba somente o código deste projeto.
3. Não suba extratos, razões, PDFs, planilhas, banco SQLite, cache ou relatórios gerados.
4. No Streamlit Community Cloud, crie um app apontando para:
   - Repository: seu repositório
   - Branch: `main`
   - Main file path: `app.py`
5. O Streamlit instalará as dependências de `requirements.txt` e usará `runtime.txt`.

Arquivos/pastas locais que ficam fora do Git:

- `.venv/`
- `data/`
- `outputs/`
- `.streamlit/secrets.toml`
- arquivos financeiros como `.csv`, `.xlsx`, `.pdf`, `.ofx` e `.txt`

## Uso via CLI

```powershell
python -m financial_reconciliation.cli `
  --bank "C:\caminho\extrato.csv" `
  --ledger "C:\caminho\razao.pdf" `
  --date-tolerance 0 `
  --value-tolerance 0 `
  --output outputs\relatorio_conciliacao.xlsx `
  --save
```

## Relatórios gerados

O Excel exportado contém:

- `Escopo`: período do extrato, período do razão, meses conciliados e aviso sobre meses fora do intervalo comum.
- `Resumo`: quantidades, totais e percentual de conciliação.
- `Resumo entradas saídas`: indicadores separados por entradas e saídas.
- `Pendências extrato`: movimentos bancários sem razão ou com divergência.
- `Pend extrato entradas` e `Pend extrato saídas`: pendências do extrato separadas por tipo.
- `Pendências razão`: lançamentos do razão sem extrato.
- `Pend razão entradas` e `Pend razão saídas`: pendências do razão separadas por tipo.
- `Matches`: correspondências e scores detalhados.
- `Matches entradas` e `Matches saídas`: correspondências separadas por tipo.
- `Duplicidades`: possíveis duplicidades por data, valor e texto.
- `Base extrato` e `Base razão`: dados normalizados para auditoria.
- `Fora período extrato` e `Fora período razão`: lançamentos ignorados por estarem fora dos meses em comum.
- Cada aba do dashboard também possui um botão próprio para exportar apenas os resultados daquela aba.

## Evolução futura

- Tela de aprovação manual para transformar correspondências parciais em aliases.
- Regras por conta bancária, centro de custo, filial e fornecedor.
- Importadores específicos por banco.
- API FastAPI para integrar com ERP/contabilidade.
- Job agendado para monitorar uma pasta de extratos e razões.
