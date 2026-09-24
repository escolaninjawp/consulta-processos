# consulta-processos

Busca e consulta de processos judiciais brasileiros nas fontes públicas, em Python.

Duas fontes, ambas oficiais e públicas do CNJ:

| Fonte | O que traz | Chave |
|---|---|---|
| **Datajud** | Metadados do processo (classe, assunto, órgão julgador, grau, datas) e todo o histórico de movimentos, inclusive os internos, que não saem no diário. **Não traz partes nem advogados** — a API pública não publica esses campos | Chave pública, já embutida |
| **Comunica / DJEN** | As publicações do Diário de Justiça Eletrônico Nacional, com o teor completo do ato, as partes e os advogados. É a única fonte pública que permite procurar por OAB | Não precisa |

As duas se completam: o Datajud tem o histórico mais completo, mas demora alguns dias para indexar; o DJEN publica no dia seguinte ao ato, e é por ele que se acompanha prazo.

## Instalação

```bash
pip install consulta-processos

# recomendado em produção (evita bloqueios em volume):
pip install "consulta-processos[navegador]"
```

Python 3.10 ou mais novo.

## Primeiro uso

Não precisa configurar nada para começar: a chave do Datajud é pública, o CNJ a divulga na [documentação da API](https://datajud-wiki.cnj.jus.br/api-publica/acesso) e ela já vem embutida. Se um dia você tiver uma chave própria, ou precisar de proxy, copie o modelo e preencha — o arquivo `.env` é lido sozinho, da pasta onde você estiver:

```bash
cp .env.exemplo .env
```

### Pela tela, no navegador

Quem não trabalha com terminal pode usar a tela:

```bash
consulta-processos web
```

O navegador abre sozinho em `http://localhost:8765`, com três abas: consultar um processo pelo número, listar os processos de um advogado pela OAB e ver as publicações do diário no período. O resultado aparece formatado, com partes, advogados, movimentações e o teor de cada publicação.

O servidor roda **só na sua máquina** — ninguém de fora acessa, e as consultas continuam indo direto do seu computador às fontes do CNJ. Não instala nada além da própria biblioteca: a página é um arquivo único, sem buscar nada na internet. Para fechar, volte ao terminal e pressione Ctrl+C.

```bash
consulta-processos web --porta 9000    # se a 8765 estiver ocupada
consulta-processos web --sem-abrir     # não abre o navegador sozinho
```

### Pelo código

```python
from consulta_processos import consultar_processo

processo = consultar_processo("1000254-20.2025.8.13.0079")

print(processo.titulo)                    # Fulano de Tal × Empresa X
print(processo.tribunal, processo.classe) # TJMG Procedimento Comum Cível
print(len(processo.movimentacoes), "movimentações")

for mov in processo.movimentacoes[:5]:
    print(f"{mov.data:%d/%m/%Y}  {mov.tipo.value}  {mov.descricao}")

for pub in processo.publicacoes[:3]:
    print(pub.data_disponibilizacao, pub.tipo_comunicacao)
    print(pub.texto[:300])                # teor do ato, já sem HTML
```

Tudo é dataclass: `processo.to_dict()` devolve um dicionário pronto para virar JSON ou registro no seu banco.

### Na linha de comando

```bash
consulta-processos web                 # a tela no navegador
consulta-processos processo 1000254-20.2025.8.13.0079
consulta-processos processo 1000254-20.2025.8.13.0079 --json > processo.json
consulta-processos oab 123456 MG --dias 60 --tribunal TJMG
consulta-processos publicacoes 123456 MG --dias 7
```

## Procurar pelo advogado: por que vem do diário

A API pública do Datajud **não publica os advogados nem as partes** do processo. Os documentos dela têm apenas número, classe, assunto, órgão julgador, grau, datas e a lista de movimentos. Procurar advogado ali devolve zero, sempre — não é falta de chave nem erro de consulta.

Quem indexa OAB é o diário (DJEN). Então `buscar_por_oab` reúne as publicações daquela inscrição no período e agrupa por processo. Duas consequências:

- o resultado é **o que saiu publicado no período**, não a carteira inteira do advogado. Um processo parado há meses não aparece: aumente `dias` para alcançar mais;
- as partes e os advogados vêm da publicação, que costuma trazê-los completos.

Sabendo o número do processo, `consultar_processo` junta as duas fontes e aí sim o histórico fica completo.

## O que dá para fazer

```python
from datetime import date, timedelta
from consulta_processos import (CNJ, buscar_por_oab, consultar_processo,
                                existe, publicacoes_por_oab)

# 1. Ler o número sem consultar nada: o próprio número diz o tribunal
cnj = CNJ("10002542020258130079")
cnj.valido, cnj.formatado, cnj.tribunal, cnj.ano
# (True, '1000254-20.2025.8.13.0079', 'TJMG', 2025)

# 2. Processo completo (Datajud + diário)
processo = consultar_processo("1000254-20.2025.8.13.0079")

# 3. Só checar se já existe — útil para processo recém-distribuído
achou, fonte = existe("1000254-20.2025.8.13.0079")

# 4. Processos em que a OAB foi publicada no período (vem do diário, não do Datajud)
processos = buscar_por_oab("123456", "MG", dias=60, tribunal="TJMG")

# 5. Publicações da semana — é assim que se monta o controle de prazos
hoje = date.today()
publicacoes = publicacoes_por_oab("123456", "MG",
                                  inicio=hoje - timedelta(days=7), fim=hoje,
                                  paginas=0)   # 0 = todas as páginas
for pub in publicacoes:
    print(pub.numero_processo, pub.tipo_comunicacao, pub.orgao)
```

### Quando a fonte está fora do ar

```python
from consulta_processos import FonteIndisponivel, consultar_processo

try:
    processo = consultar_processo("1000254-20.2025.8.13.0079")
except FonteIndisponivel as e:
    print("tente de novo mais tarde:", e)
```

O Datajud é público e gratuito, e em horário cheio chega a levar mais de um minuto por consulta (ele informa o tempo gasto no campo `took` da própria resposta). Por isso a espera padrão é de 90 segundos. Em tela, com alguém esperando, use um tempo curto e deixe o diário responder primeiro:

```python
from consulta_processos.fontes import datajud
processo = datajud.consultar_processo(numero, timeout=12)   # desiste rápido
```

`FonteIndisponivel` significa que a API não respondeu — vale repetir. Já `None` como retorno significa que as fontes responderam e o processo não existe nelas: repetir não adianta (a não ser que ele acabe de ser distribuído).

## Configuração

Tudo vem de variáveis de ambiente (veja `.env.exemplo`), ou você monta na mão:

```python
from consulta_processos import Config, consultar_processo

config = Config(datajud_api_key="...", comunica_timeout=20)
processo = consultar_processo("1000254-20.2025.8.13.0079", config=config)
```

| Variável | Para que serve |
|---|---|
| `DATAJUD_API_KEY` | Chave pública do Datajud, publicada na [documentação do CNJ](https://datajud-wiki.cnj.jus.br/api-publica/acesso) |
| `CONSULTA_PROXIES` | Lista fixa de proxies, separada por vírgula |
| `CONSULTA_GATEWAY_*` | Gateway residencial que abre um IP por porta |
| `PROXYSELLER_API_KEY` | Exemplo de provedor com API de listagem |
| `CONSULTA_USER_AGENT_EXTRA` | Identificação sua no User-Agent |
| `CONSULTA_PAUSA_PAGINAS` | Pausa entre páginas de uma busca |

### Precisa de proxy?

Quase sempre não. A API do Comunica é do gov.br e recusa requisições vindas de fora do Brasil (HTTP 403); rodando de um IP brasileiro, com volume normal, basta instalar e usar.

Proxy passa a fazer diferença quando você roda de servidor fora do país ou consulta em massa. Se houver pool configurado, a biblioteca dispara algumas tentativas em paralelo e fica com a primeira boa: em pool residencial sempre há IPs lentos, e esperar um por vez deixa a consulta arrastada.

## Como usar com bom senso

São serviços públicos, mantidos com dinheiro público e usados por todo mundo ao mesmo tempo. Vale:

- consultar o que você precisa, não a base inteira;
- guardar em cache o que já consultou, em vez de repetir a mesma consulta;
- usar `CONSULTA_PAUSA_PAGINAS` em varreduras grandes;
- identificar-se em `CONSULTA_USER_AGENT_EXTRA`;
- rodar as varreduras fora do horário de pico.

A biblioteca não contorna captcha nem qualquer proteção de tribunal: só conversa com as duas APIs públicas do CNJ, do jeito documentado. Os dados processuais são públicos, mas processo em segredo de justiça não aparece nessas fontes, e dado pessoal que você guardar continua sujeito à LGPD — trate os dados dos clientes com o mesmo cuidado que você trata os autos.

## Desenvolvimento

```bash
git clone <url-do-repositorio>
cd consulta-processos
python -m venv .venv && . .venv/Scripts/activate   # Linux/macOS: . .venv/bin/activate
pip install -e ".[dev,navegador]"
pytest
```

Os testes não acessam a rede: usam respostas gravadas das APIs.

## Licença

MIT — veja [LICENSE](LICENSE).
