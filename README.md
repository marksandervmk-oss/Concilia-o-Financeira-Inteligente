# Sistema de Conciliacao Financeira Inteligente

Projeto reutilizavel para comparar extratos bancarios com razao contabil/financeiro, encontrar pendencias e gerar relatorios de auditoria.

## O que o sistema faz

- Importa CSV, XLSX, PDF, OFX e TXT.
- Padroniza datas, valores, historicos, fornecedores e tipos de movimento.
- Remove acentos, caracteres especiais e palavras irrelevantes como LTDA, ME, EIRELI, PAGAMENTO, PIX e TED.
- Compara extrato e razao por valor exato, data exata, historico, direcao do movimento e historico de equivalencias.
- Usa fuzzy matching com RapidFuzz quando instalado e fallback com `difflib`.
- Usa PyMuPDF para acelerar a leitura de PDFs grandes, com fallback para `pypdf`.
- Classifica cada achado como alta, media ou baixa confianca.
- Gera Excel com resumo, pendencias, matches, duplicidades e bases normalizadas.
- Salva analises e aliases em SQLite para melhorar reconciliacoes futuras.

## Arquitetura

```text
financial_reconciliation/
  config.py                 Parametros do motor e thresholds
  models.py                 Modelo canonico de transacoes
  normalization.py          Limpeza textual, acentos, stopwords e tokens
  fuzzy.py                  Similaridade textual com RapidFuzz/fallback
  matching.py               Motor de conciliacao e classificacao
  database.py               SQLite para analises e memoria de aliases
  reports.py                Exportacao Excel
  cli.py                    Execucao por linha de comando
  parsers/
    csv_parser.py           CSV/TSV bancario
    excel_parser.py         XLSX/XLS
    pdf_ledger_parser.py    Razao em PDF por extracao de texto
    ofx_parser.py           OFX com biblioteca opcional ou regex
    txt_parser.py           TXT delimitado ou linhas de extrato
    universal.py            Roteador por extensao
app.py                      Dashboard Streamlit
```

## Algoritmo de matching

1. Carrega todos os arquivos para um modelo unico: data, valor, direcao, historico, fornecedor, conta, origem e linha.
2. Normaliza texto removendo acentos, pontuacao, termos societarios e termos bancarios irrelevantes.
3. Para cada lancamento do extrato, busca candidatos no razao com a mesma data e o mesmo valor.
4. Calcula score ponderado:
   - Valor: 34%
   - Data: 24%
   - Similaridade textual: 32%
   - Tipo/direcao do movimento: 10%
   - Bonus de equivalencia aprendida no SQLite quando houver alias confirmado em analises anteriores
5. Faz selecao um-para-um pelo maior score.
6. Classifica o resultado:
   - `Conciliado`
   - `Nao encontrado no razao`
   - `Nao encontrado no extrato`
   - `Divergencia de valor`
   - `Divergencia de data`
   - `Possivel duplicidade`
   - `Correspondencia parcial`

## Uso via interface

```powershell
streamlit run app.py
```

Depois, abra `http://localhost:8501`.

## Publicacao online

Opcao recomendada: GitHub privado + Streamlit Community Cloud.

1. Crie um repositorio privado no GitHub.
2. Suba somente o codigo deste projeto.
3. Nao suba extratos, razoes, PDFs, planilhas, banco SQLite, cache ou relatorios gerados.
4. No Streamlit Community Cloud, crie um app apontando para:
   - Repository: seu repositorio
   - Branch: `main`
   - Main file path: `app.py`
5. O Streamlit instalara as dependencias de `requirements.txt` e usara `runtime.txt`.

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

## Relatorios gerados

O Excel exportado contem:

- `Resumo`: quantidades, totais e percentual de conciliacao.
- `Pendencias extrato`: movimentos bancarios sem razao ou com divergencia.
- `Pendencias razao`: lancamentos do razao sem extrato.
- `Matches`: correspondencias e scores detalhados.
- `Duplicidades`: possiveis duplicidades por data, valor e texto.
- `Base extrato` e `Base razao`: dados normalizados para auditoria.

## Evolucao futura

- Tela de aprovacao manual para transformar correspondencias parciais em aliases.
- Regras por conta bancaria, centro de custo, filial e fornecedor.
- Importadores especificos por banco.
- API FastAPI para integrar com ERP/contabilidade.
- Job agendado para monitorar uma pasta de extratos e razoes.
