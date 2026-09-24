# consulta-processos

Busca e consulta de processos judiciais brasileiros nas fontes públicas, em Python.

Duas fontes, ambas oficiais e públicas do CNJ:

| Fonte | O que traz | Chave |
|---|---|---|
| **Datajud** | Metadados do processo (classe, assunto, órgão, valor, partes) e todo o histórico de movimentos, inclusive os internos, que não saem no diário | Chave pública, publicada pelo CNJ |
| **Comunica / DJEN** | As publicações do Diário de Justiça Eletrônico Nacional, com o teor completo do ato, as partes e os advogados | Não precisa |

As duas se completam: o Datajud tem o histórico mais completo, mas demora alguns dias para indexar; o DJEN publica no dia seguinte ao ato, e é por ele que se acompanha prazo.

## Instalação

```bash
pip install consulta-processos

# recomendado em produção (evita bloqueios em volume):
pip install "consulta-processos[navegador]"
```

Python 3.10 ou mais novo.

## Primeiro uso

```bash
cp .env.exemplo .env      # e preencha DATAJUD_API_KEY
```

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
consulta-processos processo 1000254-20.2025.8.13.0079
consulta-processos processo 1000254-20.2025.8.13.0079 --json > processo.json
consulta-processos oab 123456 MG --tribunal TJMG
consulta-processos publicacoes 123456 MG --dias 7
```

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

# 4. Carteira de um advogado (informe o tribunal: sem ele, varre todos e demora)
processos = buscar_por_oab("123456", "MG", tribunal="TJMG")

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
