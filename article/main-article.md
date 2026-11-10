CENTRO ESTADUAL DE EDUCAÇÃO TECNOLÓGICA PAULA SOUZA

FACULDADE DE TECNOLOGIA DA BAIXADA SANTISTA

CURSO SUPERIOR DE TECNOLOGIA EM CIÊNCIA DE DADOS

RELATÓRIO TÉCNICO

**PREVISÃO DE FALHAS EM DISCOS RÍGIDOS COM ATRIBUTOS SMART: análise de sobrevivência sobre o *dataset* Drive Stats da Backblaze**

Kauan Toledo Camargo (Graduando em Ciência de Dados, Fatec Rubens Lara) kauan.camargo01@aluno.cps.sp.gov.br

SANTOS

NOVEMBRO/2026

# RESUMO

A falha de um disco rígido em um *data center* obriga o operador a reconstruir dados a partir de cópias redundantes, e prevê-la permite planejar a substituição. Este relatório avalia se os atributos de Tecnologia de Automonitoramento, Análise e Relatório (SMART), lidos diariamente pelo `smartctl`, permitem estimar a probabilidade e o momento provável de falha de discos rígidos. Utilizou-se o *dataset* público Drive Stats, da Backblaze, com 646.777.037 registros diários de 478.464 unidades (2016–2025). O problema foi formulado como análise de sobrevivência em tempo discreto, com censura à direita, e estimado por *gradient boosting* sobre uma amostra ponderada de 57.309 discos; a avaliação usou discos e anos não vistos no treino. No horizonte de 30 dias, os atributos SMART elevaram a área sob a curva *Receiver Operating Characteristic* de 0,603 para 0,877, e cerca de 61% desse ganho permaneceu sem os contadores que o operador usa para decidir substituições. Com limiar fixado para 1% de falsos alarmes, o modelo alertou 78% dos discos que falharam (67% com sete dias ou mais de antecedência), contra 59% de uma regra simples de contadores SMART; a taxa de falsos alarmes medida foi de 1,87%, e a precisão, de 3,8%, ambas por dia de disco. As falhas sem sinal nesses contadores, cerca de 21% do total, foram pouco previsíveis, e as probabilidades superestimaram o risco em 2025. Conclui-se que os atributos SMART são úteis para priorizar inspeções a curto prazo, mas que o estudo não demonstra estimativas precisas da data de falha.

Palavras-chave: análise de sobrevivência; atributos SMART; discos rígidos; manutenção preditiva; aprendizado de máquina.

# LISTA DE ILUSTRAÇÕES

Figura 1 – Fluxo das etapas de tratamento de dados e modelagem

Figura 2 – ROC-AUC por horizonte no conjunto de teste, com intervalos de confiança de 95%

Figura 3 – Proporção de retratos de discos que falham com alerta, por dias até a falha (limiar do orçamento de 1%)

Figura 4 – Calibração por decil de risco no conjunto de teste, por horizonte (escalas logarítmicas)

Quadro 1 – Principais atributos SMART utilizados

Quadro 2 – Modelos comparados

# LISTA DE TABELAS

Tabela 1 – Composição da coorte por conjunto e estrato

Tabela 2 – ROC-AUC por horizonte de previsão no conjunto de teste

Tabela 3 – Raridade do evento e precisão média do modelo principal, por horizonte e por estimador

Tabela 4 – ROC-AUC em 30 dias por modelo e por recorte do conjunto de teste

Tabela 5 – Desempenho dos alertas no conjunto de teste, por orçamento de falsos alarmes

Tabela 6 – Retratos de discos que falham com mediana prevista dentro de um ano, por distância real até a falha

Tabela 7 – Risco de falha em 30 dias previsto e observado, por conjunto e ano

# LISTA DE ABREVIATURAS E SIGLAS

| Sigla | Significado |
|---|---|
| F1 | Medida F1 (média harmônica entre precisão e revocação) |
| GB | *Gigabyte* |
| GiB | *Gibibyte* |
| HDD | *Hard Disk Drive* (disco rígido) |
| IPCW | *Inverse Probability of Censoring Weighting* (ponderação pelo inverso da probabilidade de censura) |
| PR-AUC | Área sob a curva de precisão e revocação, estimada pela precisão média |
| RAID | *Redundant Array of Independent Disks* |
| ROC | *Receiver Operating Characteristic* |
| ROC-AUC | Área sob a curva ROC |
| SHA-256 | *Secure Hash Algorithm* de 256 bits |
| SMART | *Self-Monitoring, Analysis and Reporting Technology* (Tecnologia de Automonitoramento, Análise e Relatório) |
| SQL | *Structured Query Language* |
| SSD | *Solid State Drive* (unidade de estado sólido) |
| TB | *Terabyte* |

# SUMÁRIO

1 INTRODUÇÃO

1.1 OBJETIVO GERAL

1.2 OBJETIVOS ESPECÍFICOS

2 CONTEXTUALIZAÇÃO DO CENÁRIO

2.1 ATRIBUTOS SMART E FALHAS DE DISCOS EM CAMPO

2.2 O *DATASET* DA BACKBLAZE E A DEFINIÇÃO DE FALHA

2.3 AVALIAÇÃO DE MODELOS: VAZAMENTO, EVENTOS RAROS E DERIVA

2.4 ANÁLISE DE SOBREVIVÊNCIA EM TEMPO DISCRETO E CENSURA

2.5 AMOSTRAGEM, PONDERAÇÃO E CALIBRAÇÃO

2.6 LACUNA E POSICIONAMENTO DO ESTUDO

3 PROCEDIMENTOS METODOLÓGICOS

3.1 APRESENTAÇÃO DO *DATASET*

3.2 DETALHAMENTO DAS ETAPAS DE TRATAMENTO DE DADOS E FERRAMENTAS

4 RESULTADOS DA ANÁLISE E RECOMENDAÇÕES

4.1 GANHO DOS ATRIBUTOS SMART

4.2 POLÍTICA DE SUBSTITUIÇÃO, USO E FALHAS SILENCIOSAS

4.3 ALERTA ANTECIPADO

4.4 VIDA ÚTIL REMANESCENTE

4.5 CALIBRAÇÃO, DERIVA E RETIRADA DE DISCOS

4.6 COMPARAÇÕES COMPLEMENTARES E SENSIBILIDADE

4.7 RECOMENDAÇÕES

5 CONSIDERAÇÕES FINAIS E LIMITAÇÕES DO ESTUDO

REFERÊNCIAS

APÊNDICE A – GUIA DE REPRODUÇÃO DOS RESULTADOS


# 1 INTRODUÇÃO

Em *data centers* de armazenamento, a falha de um disco rígido (*Hard Disk Drive*, HDD) obriga o operador a reconstruir os dados a partir de cópias redundantes, e falhas próximas no tempo em um mesmo grupo de discos podem causar perda de dados (MA *et al.*, 2015). Prever quais discos tendem a falhar permite substituí-los de forma planejada, antes que a falha ocorra.

Os próprios discos registram indicadores internos por meio da Tecnologia de Automonitoramento, Análise e Relatório (*Self-Monitoring, Analysis and Reporting Technology*, SMART). Esses indicadores, chamados atributos SMART, são lidos por ferramentas como o `smartctl`, do pacote *smartmontools*, e incluem contadores de setores realocados, de erros não corrigidos e de horas de funcionamento. A questão que orienta este relatório é se esses atributos permitem estimar a probabilidade de falha de um disco e o momento provável em que ela ocorrerá.

O estudo delimita-se aos discos rígidos do *dataset* público Drive Stats, publicado pela empresa de armazenamento em nuvem Backblaze, no período de 1º de janeiro de 2016 a 31 de dezembro de 2025. O painel bruto reúne 646.777.037 registros diários de 478.464 números de série, incluídas as unidades de estado sólido (*Solid State Drives*, SSD), que foram excluídas da análise por constituírem outra população de falhas. Os resultados referem-se à carga de trabalho de um *data center* de armazenamento e ao critério de falha desse operador, e não se estendem automaticamente a outros operadores nem a computadores pessoais.

A relevância do tema para a formação do tecnólogo em Ciência de Dados reside na combinação de problemas que o estudo exige tratar: volume de dados acima da memória disponível, eventos raros, observações incompletas (discos retirados antes de falhar ou ainda em operação ao fim do período) e risco de vazamento de informação entre treino e teste. Para o mercado, o estudo fornece critérios para decidir se um sistema de alerta baseado em SMART compensa o custo de falsos alarmes. O público-alvo compreende gestores de infraestrutura de *data centers*, equipes de operação de armazenamento e analistas que desenvolvem modelos de manutenção preditiva.

## 1.1 OBJETIVO GERAL

Avaliar se os atributos SMART coletados diariamente pelo `smartctl` permitem estimar a probabilidade e o momento provável de falha de discos rígidos em operação nos *data centers* da Backblaze, quantificando o ganho que oferecem em relação às informações disponíveis sem eles.

## 1.2 OBJETIVOS ESPECÍFICOS

a) estruturar a previsão de falhas como problema de análise de sobrevivência em tempo discreto, com tratamento de censura à direita;

b) mensurar o ganho de discriminação dos atributos SMART em relação a um modelo que usa apenas o modelo comercial do disco, o fabricante, a capacidade, o tempo de serviço e o indicador de disco já em operação no início do painel;

c) verificar, por ablação, quanto desse ganho permanece quando se retiram do modelo os contadores usados pelo operador para decidir substituições;

d) avaliar o desempenho do modelo como sistema de alerta antecipado sob orçamentos fixos de falsos alarmes;

e) verificar a calibração das probabilidades e das estimativas de vida útil remanescente, bem como sua estabilidade ao longo do tempo.

# 2 CONTEXTUALIZAÇÃO DO CENÁRIO

## 2.1 ATRIBUTOS SMART E FALHAS DE DISCOS EM CAMPO

O SMART foi concebido como mecanismo interno de alerta: o próprio disco aciona um sinal binário quando algum atributo ultrapassa um limite definido pelo fabricante. Murray *et al.* (2005) relatam que, com esse algoritmo de limites, os fabricantes estimam a taxa de detecção de falhas entre 3% e 10%, e que testes estatísticos não paramétricos sobre os mesmos atributos detectam uma parcela maior de falhas.

Os estudos de campo publicados em 2007 mostraram que a confiabilidade observada difere da especificada. Schroeder e Gibson (2007), ao analisar registros de substituição de cerca de 100 mil discos, constataram taxas anuais de substituição tipicamente acima de 1%, frequentemente entre 2% e 4% e de até 13%, valores superiores aos derivados do tempo médio até a falha informado pelos fabricantes. O evento analisado por esses autores é a substituição do disco, e não a falha física comprovada, distinção que reaparece no *dataset* deste estudo (seção 2.2).

No mesmo ano, Pinheiro *et al.* (2007) analisaram uma população de discos da Google e identificaram atributos SMART fortemente associados à falha: após o primeiro erro de varredura, um disco tinha 39 vezes mais probabilidade de falhar nos 60 dias seguintes do que um disco sem esse erro. Os mesmos autores, porém, verificaram que mais de 56% dos discos que falharam não apresentavam contagem em nenhum dos quatro sinais mais fortes e que mais de 36% não apresentavam contagem em nenhum dos atributos analisados, exceto a temperatura. Concluíram que "modelos baseados apenas em parâmetros SMART dificilmente serão úteis para prever falhas de discos individuais" (PINHEIRO *et al.*, 2007, p. 17, tradução nossa). Essas falhas sem sinal prévio nos contadores são denominadas, neste relatório, falhas silenciosas.

Outros trabalhos detalham o mecanismo por trás dos contadores. Bairavasundaram *et al.* (2007) acompanharam 1,53 milhão de discos por 32 meses e mostraram que erros latentes de setor apresentam localidade temporal e espacial, isto é, um disco que começa a acumular erros tende a continuar acumulando-os. Ma *et al.* (2015) verificaram que a contagem de setores realocados se correlaciona fortemente com falhas iminentes e relatam que a substituição proativa com base nesse contador eliminou 88% dos erros triplos de disco em grupos de *Redundant Array of Independent Disks* (RAID). Em sentido complementar, Lu *et al.* (2020), com dados de 380 mil discos distribuídos em 64 *data centers*, mostraram que métricas de desempenho do sistema combinadas aos atributos SMART superam o uso exclusivo dos atributos SMART.

## 2.2 O *DATASET* DA BACKBLAZE E A DEFINIÇÃO DE FALHA

A Backblaze registra diariamente um retrato (*snapshot*) de cada disco em operação, com informações básicas da unidade e os atributos SMART reportados, e publica esses registros em arquivos diários (BACKBLAZE, 2026). O esquema de colunas muda de um trimestre para outro, o que exige alinhamento dos dados antes de qualquer análise. O conjunto tornou-se referência em pesquisa: a empresa contabiliza ao menos 227 artigos que o utilizam como fonte primária desde 2018 (DOYLE, 2026).

A definição de falha adotada pelo operador é central para a interpretação de qualquer modelo treinado nesse *dataset*. Beach (2014) informa que a Backblaze considera falho o disco removido e substituído por ter parado de funcionar ou por apresentar evidência de falha iminente, e que essa evidência vem dos atributos SMART 5, 187, 188, 197 e 198. Sobre o atributo 187, o autor afirma: "assim que o SMART 187 fica acima de zero, a substituição do disco é programada" (BEACH, 2014, não paginado, tradução nossa). Klein (2024) classifica as falhas em reativas (o disco não inicia, não responde ou não permanece operacional) e proativas (indicadores como SMART ou verificações do sistema de arquivos apontam falha provável); no terceiro trimestre de 2024, 53,0% das 1.361 falhas foram proativas, e o *dataset* público registra apenas o indicador binário de falha, sem o tipo. Em 2025, a empresa descreveu um monitor que remove o acesso a discos cujo número de erros não corrigidos ultrapassa um limite e regras baseadas em chamados de manutenção para decidir se um disco falhou; no mesmo relatório, um modelo Toshiba de 16 *terabytes* (TB) apresentou taxa anualizada de falhas de 16,95% no terceiro trimestre de 2025, em razão de retiradas ligadas a uma atualização de *firmware*, falha que, segundo a empresa, não era mecânica (BACKBLAZE, 2025).

Disso decorre um problema de circularidade: parte do rótulo de falha é definida pelos mesmos contadores SMART que o modelo usa como variáveis explicativas. Um modelo que aprende que o atributo 187 acima de zero precede a falha pode estar aprendendo a política de substituição do operador, e não a degradação física do disco. Klein (2016) mostra a dimensão do fenômeno: 76,7% dos discos falhos e 4,2% dos discos em operação tinham ao menos um dos cinco atributos acima de zero, de modo que 23,3% das falhas ocorreram sem aviso nesses atributos.

Há ainda particularidades de codificação. O `smartctl` oferece formatos de leitura específicos para atributos cujo valor bruto (*raw*) reúne vários campos, como três inteiros de 16 bits ou horas e milissegundos, e seu banco de dados de unidades aplica esses formatos aos atributos 188 e 240 de famílias de discos Seagate (SMARTMONTOOLS, 2025). Lidos como um único inteiro, esses valores não representam contagens e exigem tratamento antes do uso como variável numérica.

## 2.3 AVALIAÇÃO DE MODELOS: VAZAMENTO, EVENTOS RAROS E DERIVA

Kapoor e Narayanan (2023) identificaram vazamento de dados (*data leakage*) em pelo menos 294 artigos de 17 áreas que empregam aprendizado de máquina, e incluem, entre os tipos descritos, a dependência temporal e a falta de independência entre amostras de treino e teste. Na previsão de falhas de discos, o efeito é mensurável. Xu *et al.* (2018), em dados de produção da Microsoft, obtiveram taxa de verdadeiros positivos de 91,64% com validação cruzada aleatória e de 36,50% com divisão temporal, ambas a 0,1% de falsos positivos, e concluíram que a validação cruzada nem sempre reflete a eficácia real de um modelo de previsão. Lu *et al.* (2020, p. 158) avaliaram seus modelos com validação cruzada aleatória em cinco partições, o que torna seus resultados não comparáveis aos de uma divisão por disco e por tempo.

Falhas são eventos raros, e a área sob a curva *Receiver Operating Characteristic* (ROC-AUC) pode ser enganosa nessa condição: Saito e Rehmsmeier (2015) mostram que a curva de precisão e revocação é mais informativa que a curva ROC em dados desbalanceados. Por esse motivo, a área sob a curva de precisão e revocação (PR-AUC) deve acompanhar a ROC-AUC. Na literatura sobre o *dataset* da Backblaze, Han *et al.* (2023) avaliam seus modelos com taxa de falsos positivos fixada em 1%, calculada por dia e tomada em média no período de avaliação, e mostram que a distribuição dos atributos muda ao longo do tempo, fenômeno que denominam deriva de conceito (*concept drift*); a adaptação a essa deriva elevou a medida F1 (média harmônica entre precisão e revocação) de seus modelos entre 26,8% e 53,2%. Amram *et al.* (2021), com árvores ótimas de sobrevivência e de classificação no mesmo *dataset*, relatam sensibilidade de aproximadamente 50% com taxa de falsos alarmes próxima de 10% para horizontes de 30 a 90 dias.

## 2.4 ANÁLISE DE SOBREVIVÊNCIA EM TEMPO DISCRETO E CENSURA

Um classificador binário responde se o disco falhará dentro de um único horizonte, fixado de antemão, e exige decidir o rótulo de discos cujo destino é desconhecido: discos retirados sem falha e discos ainda em operação ao fim do período de observação. Esses casos são observações censuradas à direita. Vock *et al.* (2016) mostram que descartá-los ou tratá-los como não eventos são técnicas *ad hoc* que introduzem viés na estimativa do risco. Na Backblaze, a censura é frequente: Siemroth e Park (2026) contabilizaram 146.943 discos, cerca de 31% de sua amostra, retirados sem falha, e os trataram como censurados à direita.

A análise de sobrevivência em tempo discreto acomoda a censura e produz, com um único modelo, uma distribuição do tempo até a falha coerente entre horizontes. O futuro de cada observação é dividido em intervalos, e cada observação gera uma linha por intervalo em que permanece em risco (formato pessoa-período). Suresh *et al.* (2022) mostram que, como a verossimilhança desse formato é binomial, qualquer algoritmo capaz de otimizar uma verossimilhança binomial estima os riscos por intervalo, inclusive classificadores de aprendizado de máquina; os autores alertam que o desempenho varia com o número de intervalos escolhido.

A avaliação de modelos de sobrevivência também exige cuidados com a censura. Uno *et al.* (2011) mostram que a estatística C de Harrell (HARRELL *et al.*, 1982) converge para uma medida que depende da distribuição de censura do estudo e propõem um estimador ponderado que, sob censura independente, não depende dela. Quando a censura decorre do encerramento da coleta em uma data fixa (censura administrativa), o tempo máximo de acompanhamento de cada observação é conhecido de antemão. Kvamme e Borgan (2023) mostram que, nesse caso, o escore de Brier ponderado pelo inverso da probabilidade de censura (*Inverse Probability of Censoring Weighting*, IPCW) pode ser enviesado quando as covariáveis informam o tempo de censura, o que ocorre se a distribuição das covariáveis muda com o tempo de calendário, e propõem uma versão do escore que usa os tempos de censura conhecidos, sem estimar a distribuição de censura. Xu *et al.* (2026) descrevem o vazamento correspondente no treino: se as variáveis revelam a data da observação, o modelo pode aprender quanto acompanhamento havia disponível, e não o risco real, o que infla a ROC-AUC em horizonte fixo. Esses autores recomendam que uma tarefa de previsão em horizonte H só use observações com pelo menos H de acompanhamento possível.

## 2.5 AMOSTRAGEM, PONDERAÇÃO E CALIBRAÇÃO

Com eventos raros e dados volumosos, é comum amostrar todos os eventos e uma fração dos não eventos, corrigindo depois as estimativas por ajuste das probabilidades a priori ou por ponderação pelo inverso da probabilidade de inclusão (KING; ZENG, 2001). Sugiyama *et al.* (2007), no contexto de mudança na distribuição das covariáveis, observam que a ponderação completa é consistente, mas pode ser instável, e descrevem uma variante que eleva os pesos de importância a um expoente entre 0 e 1, que controla a troca entre consistência e estabilidade; os autores propõem escolher esse expoente por validação cruzada ponderada pela importância.

Alterar o peso relativo das classes tem custo na calibração: Van den Goorbergh *et al.* (2022) verificaram que correções de desbalanceamento levaram a superestimação acentuada das probabilidades sem melhorar a ROC-AUC. Uma recalibração posterior pode corrigir a distorção. Niculescu-Mizil e Caruana (2005) mostram que árvores com *boosting* produzem distorção em forma sigmoide, corrigida pelo escalonamento de Platt, um ajuste logístico de dois parâmetros.

Por fim, observações diárias de um mesmo disco são quase idênticas e não são independentes. Pang *et al.* (2023) mostram que o *bootstrap* por agrupamento, que reamostra unidades inteiras em vez de linhas, atinge cobertura adequada para intervalos de confiança da ROC-AUC com dados correlacionados.

## 2.6 LACUNA E POSICIONAMENTO DO ESTUDO

Os trabalhos revisados deixam dois pontos em aberto para o *dataset* da Backblaze. O primeiro é a circularidade do rótulo: os estudos de previsão consultados sobre esse *dataset* (AMRAM *et al.*, 2021; HAN *et al.*, 2023) usam o indicador de falha como publicado, sem verificar quanto do desempenho depende dos contadores que o operador usa para decidir substituições. O segundo é a avaliação: resultados obtidos com validação cruzada aleatória não indicam o desempenho em discos e períodos novos (XU *et al.*, 2018), e a ROC-AUC isolada não indica o desempenho na prevalência real do evento (SAITO; REHMSMEIER, 2015). Quanto ao momento da falha, Amram *et al.* (2021) já empregam modelos de sobrevivência nesse *dataset*; aqui, examinam-se adicionalmente os quantis de vida útil remanescente e os limites de sua avaliação. A contribuição deste relatório está na combinação dessas análises: um modelo de sobrevivência em tempo discreto, avaliado em discos e anos não vistos no treino, com métricas ponderadas para a prevalência do evento na população estudada e com ablações que retiram do modelo os contadores usados pelo operador.

# 3 PROCEDIMENTOS METODOLÓGICOS

Adotou-se abordagem quantitativa, de caráter descritivo e preditivo, fundamentada em dados secundários. O problema foi formulado como análise de sobrevivência em tempo discreto, e o efeito dos atributos SMART foi medido por comparação entre modelos que diferem apenas no conjunto de variáveis de entrada (ablação). Todo o processamento foi implementado como um *pipeline* reprodutível, descrito na seção 3.2 e no APÊNDICE A.

## 3.1 APRESENTAÇÃO DO *DATASET*

Selecionou-se o *dataset* Drive Stats da Backblaze por três razões. Quanto à confiabilidade, os registros são coletados de forma automatizada, todos os dias, com o pacote *smartmontools*, nos discos em produção do operador (BEACH, 2014). Quanto à credibilidade, a empresa coleta e publica os dados desde 2013 (BACKBLAZE, 2026), e o conjunto é utilizado como fonte primária em ao menos 227 trabalhos (DOYLE, 2026), entre eles estudos revisados por pares sobre previsão de falhas e confiabilidade de discos (AMRAM *et al.*, 2021; HAN *et al.*, 2023; SIEMROTH; PARK, 2026). Quanto à aplicabilidade, entre as fontes consultadas, é o *dataset* público que combina atributos SMART diários, indicador de falha e uma década de acompanhamento de centenas de milhares de discos, o que permite estimar curvas de sobrevivência e avaliar o modelo em anos posteriores aos de treino.

Utilizou-se o painel de 1º de janeiro de 2016 a 31 de dezembro de 2025, armazenado em um único arquivo Parquet de cerca de 21,8 *gibibytes* (GiB). Antes de qualquer filtro, o painel contém 646.777.037 linhas, uma por unidade e por dia, de 478.464 números de série, dos quais 26.679 têm ao menos um registro de falha; essas contagens incluem os SSD. A integridade do arquivo é verificada pelo resumo criptográfico *Secure Hash Algorithm* de 256 bits (SHA-256) antes da varredura do painel, de modo que qualquer alteração no arquivo é detectada antes da análise. Cada linha contém as seguintes variáveis:

a) **date**: data do registro diário;

b) **serial_number**: número de série, que identifica o disco;

c) **model** e **capacity_bytes**: modelo comercial e capacidade da unidade;

d) **failure**: indicador binário igual a 1 no último dia operacional de um disco considerado falho pelo operador;

e) **smart_N_raw** e **smart_N_normalized**: valor bruto e valor normalizado de cada atributo SMART N reportado pelo disco.

O Quadro 1 apresenta os atributos SMART mais relevantes para a análise. A lista completa de atributos utilizados é fixada antes da modelagem (seção 3.2).

**Quadro 1 – Principais atributos SMART utilizados**

| Atributo | Nome | Papel na análise |
|---|---|---|
| 5 | *Reallocated Sectors Count* (setores realocados) | contador crítico; usado na regra dos contadores críticos |
| 187 | *Reported Uncorrectable Errors* (erros não corrigidos reportados) | contador crítico; usado na regra dos contadores críticos |
| 188 | *Command Timeout* (comandos expirados) | usado pela Backblaze na decisão de substituição; apenas o valor normalizado é variável do modelo |
| 197 | *Current Pending Sector Count* (setores pendentes) | contador crítico; usado na regra dos contadores críticos |
| 198 | *Offline Uncorrectable* (erros não corrigíveis em varredura) | contador crítico; usado na regra dos contadores críticos |
| 9 | *Power-On Hours* (horas ligado) | idade e uso |
| 4, 12, 193 | partidas e paradas, ciclos de energia, ciclos de carga do cabeçote | uso |
| 240, 241, 242 | horas de voo do cabeçote, blocos lógicos gravados e lidos | uso |

Fonte: Elaborado pelo autor com base em Beach (2014) e no arquivo de configuração `config/study.toml` do projeto.

Na preparação, foram tratadas as seguintes particularidades do painel:

a) **unidades de estado sólido**: 3.898 SSD foram excluídos por padrão de nome de modelo;

b) **nomes de modelo**: a quantidade de espaços em branco nos nomes varia entre anos e foi normalizada;

c) **linhas duplicadas no mesmo dia**: manteve-se uma linha por disco e por dia, a mais completa;

d) **registros após a falha**: 710 unidades do painel bruto (694 discos rígidos e 16 SSD) continuam reportando após o primeiro registro de falha, das quais 561 pertencem à coorte analisada; considerou-se a primeira falha como o evento e descartaram-se as linhas posteriores;

e) **colunas em texto**: atributos armazenados como texto foram convertidos para número, com contagem dos valores que falham na conversão;

f) **valores brutos compactados**: nos retratos de discos Seagate, 2,9% dos valores brutos do atributo 188 são maiores ou iguais a 65.536, e 1,1% dos valores brutos do atributo 240 são maiores ou iguais a 2³², proporções medidas neste projeto (registradas em `config/study.toml`) e compatíveis com os formatos de vários campos que a documentação do `smartctl` associa a esses atributos (SMARTMONTOOLS, 2025). Para o 188, usou-se apenas o valor normalizado; para o 240, mantiveram-se os 32 bits inferiores, que correspondem às horas nesse formato;

g) **lacunas de registro**: todas as janelas temporais são definidas por datas de calendário, e não por número de linhas, de modo que dias sem registro não deslocam as janelas das variáveis de tendência.

## 3.2 DETALHAMENTO DAS ETAPAS DE TRATAMENTO DE DADOS E FERRAMENTAS

Utilizou-se a linguagem Python 3.13, com dependências fixadas pelo gerenciador *uv*, em razão da disponibilidade de bibliotecas para dados volumosos e aprendizado de máquina. O painel completo não cabe na memória de um computador pessoal; por isso, toda operação sobre ele foi feita com o DuckDB, banco de dados analítico que executa consultas em *Structured Query Language* (SQL) diretamente sobre arquivos Parquet, percorrendo o painel em blocos de meses. A modelagem utilizou o LightGBM (KE *et al.*, 2017), implementação de *gradient boosting* em árvores de decisão escolhida por aceitar pesos por linha, variáveis categóricas, valores ausentes e treino em lotes. As etapas foram encadeadas pelo executor *data-pipeline*, que registra um ponto de verificação por etapa e só executa novamente o que depende de entradas alteradas. A execução que origina os resultados ocorreu em 9 de novembro de 2026, em um computador com processador AMD Ryzen 7 5700X e 31 GiB de memória, em cerca de 45 minutos, dos quais cerca de 4 minutos na varredura inicial do painel. Uma versão anterior do *pipeline*, executada em 26 e 27 de outubro de 2026, foi repetida em 30 de outubro em um computador com 15 GiB de memória, e todas as métricas das duas execuções diferiram em menos de 4 × 10⁻⁵ em valor absoluto. A Figura 1 apresenta o fluxo das etapas.

**Figura 1 – Fluxo das etapas de tratamento de dados e modelagem**

![Fluxo das etapas](figures/figura-1-fluxo.svg)

Fonte: Elaborado pelo autor (2026).

As etapas são descritas a seguir:

a) **indexação (drive_index)**: varredura do painel completo, mês a mês, que gera uma linha por disco com modelo, capacidade, primeira e última data observada e data da primeira falha;

b) **coorte (cohort)**: divisão dos discos em treino (70%), validação (10%) e teste (20%) por um *hash* SHA-256 do número de série, estável entre versões de bibliotecas, de modo que nenhum disco aparece em mais de um conjunto. A divisão também é temporal: dados de treino e validação vão até 31 de dezembro de 2023, e o teste começa em 1º de janeiro de 2024. Um disco só entra na coorte se tiver registros na janela de seu conjunto; 100.065 discos foram excluídos por esse critério (discos de treino ou validação vistos pela primeira vez a partir de 2024 e discos de teste que saíram do painel ou falharam antes de 2024). Restaram 374.501 discos elegíveis, sobre os quais se aplicou amostragem estratificada: os 22.230 que falham em algum momento foram mantidos, e os demais foram sorteados com probabilidade de 10% (35.079 de 352.271). Cada disco recebe peso igual ao inverso de sua probabilidade de inclusão (1 para discos que falham e 10 para os demais), conforme a estratégia de King e Zeng (2001). A população-alvo das estimativas é, portanto, a dos discos rígidos elegíveis e de seus dias registrados em cada conjunto. Com os pesos, as proporções de positivos, a precisão, a PR-AUC e a calibração referem-se a essa população, e não à amostra enriquecida com falhas; a ROC-AUC não depende da proporção entre as classes, e nela os pesos apenas restituem a composição de discos e dias dentro de cada classe. Os pesos corrigem a amostragem, mas não a censura, as lacunas de registro nem os efeitos de recortes definidos pelo desfecho, tratados adiante. A Tabela 1 apresenta a composição da coorte;

c) **extração (extract)**: leitura, com o DuckDB, das linhas diárias dos discos da coorte, restrita às colunas de interesse, sem duplicatas e cortada na primeira falha;

d) **retratos e rótulos (snapshots)**: seleção de um retrato a cada 7 dias por disco (peso 7) e de todos os dias nos 90 dias anteriores a uma falha visível no período do conjunto (peso 1), para que o período que antecede a falha seja observado em detalhe sem exceder a memória disponível; o peso final do retrato é o produto desse peso pelo peso do disco. Cada retrato recebe dois rótulos: a duração, isto é, o número de dias até a primeira falha ou até o último dia em que o disco é sabidamente operacional, e o indicador de evento (falha) ou de censura. O retrato do próprio dia da falha é mantido, com zero dias até o evento. Discos de treino e de validação são censurados em 31 de dezembro de 2023, de modo que uma falha posterior é desconhecida para o treino, e não tratada como ausência de falha (VOCK *et al.*, 2016);

e) **variáveis**: 64 variáveis fixadas antes da modelagem, e não escolhidas a partir dos dados: 23 valores brutos e 10 valores normalizados de atributos SMART; 24 variáveis de tendência, calculadas para 12 atributos escolhidos de antemão (dez contadores brutos e os valores normalizados dos atributos 1 e 7) como a diferença entre o valor atual e o primeiro valor não nulo do atributo na janela formada pelo dia do retrato e pelos 7 ou 30 dias de calendário anteriores, em linha com a localidade temporal de erros descrita por Bairavasundaram *et al.* (2007); 2 variáveis com o número de dias entre o primeiro registro do disco em cada janela e o dia do retrato; e 5 variáveis de contexto: dias em serviço (contados do primeiro registro do disco no painel, e não da fabricação), indicador de disco já em operação no primeiro dia do painel (cuja idade real é desconhecida), capacidade, modelo (os 30 modelos mais frequentes no treino, os demais agrupados) e fabricante. Valores ausentes são mantidos como ausentes e tratados pelo LightGBM, que também recebe modelo e fabricante como variáveis categóricas. A data de calendário não é variável, para reduzir o vazamento por corte administrativo descrito por Xu *et al.* (2026). Pelo mesmo motivo, modelo e capacidade não podem depender de quanto tempo o disco sobrevive: usam-se o primeiro nome de modelo e a primeira capacidade válida informados pelo disco, arredondada a 10 GB. Uma versão anterior tomava a capacidade máxima ao longo da vida do disco; como em um único dia (25 de fevereiro de 2018) o painel informa capacidades arredondadas, esse máximo revelava se o disco ainda estava em operação nessa data. Os 10 discos que nunca informam capacidade, todos com falha em poucos dias, recebem a capacidade mais comum de seu modelo. Dias em serviço e modelo do disco, porém, revelam parcialmente a data do retrato, de modo que esse risco é reduzido, e não eliminado;

f) **portão de verificação (verify)**: antes de qualquer treino, 56 verificações automáticas recalculam todos os rótulos de forma independente e conferem a separação dos conjuntos por disco e por tempo, os pesos, a densidade de amostragem, o esquema de colunas e a ausência de colunas que revelem o desfecho. Qualquer erro interrompe o *pipeline*;

g) **análise exploratória (explore)**: diagnósticos sem uso na escolha das variáveis: taxa anualizada de falhas por modelo de disco, ROC-AUC de cada atributo isolado e correlação de Spearman entre variáveis nos retratos de treino, e curvas de Kaplan-Meier dos retratos de teste com e sem contador crítico acima de zero;

h) **modelagem (train)**: o futuro de cada retrato foi dividido em sete intervalos, de 0 a 6, 7 a 13, 14 a 29, 30 a 59, 60 a 89, 90 a 179 e 180 a 364 dias, sendo 0 o dia do retrato; os intervalos são mais curtos perto do retrato, onde se concentram as decisões de operação. Cada retrato gera uma linha por intervalo em que permanece em risco (formato pessoa-período), e o LightGBM estima o risco discreto hₖ(x), isto é, a probabilidade de falha no intervalo k dado que o disco estava operacional no início desse intervalo, com o início do intervalo como variável adicional (SURESH *et al.*, 2022). A probabilidade de sobreviver até o fim do intervalo k é o produto S(tₖ) = [1 − h₁(x)] × [1 − h₂(x)] × … × [1 − hₖ(x)], e a probabilidade de falha em até H dias, isto é, nos dias 0 a H − 1, é 1 − S(H), em que S(H) é o valor desse produto ao fim do intervalo que termina no dia H − 1, para H igual a 7, 30, 90, 180 e 365. Da mesma curva, com interpolação linear de S dentro de cada intervalo, obtêm-se o dia em que a probabilidade acumulada de falha atinge 10%, 50% (mediana da vida útil remanescente) e 90%, que são quantis da distribuição prevista, e não intervalos de confiança, e o número esperado de dias operacionais no ano seguinte (área sob a curva interpolada). Além de 365 dias, o modelo não tem intervalos, e a resposta é apenas "mais de um ano". Um retrato censurado no dia d de um intervalo que vai do dia a ao dia b − 1 contribui para esse intervalo com peso multiplicado por (d − a + 1)/(b − a), a fração observada; trata-se de uma aproximação atuarial, que supõe risco uniforme dentro do intervalo e é mais grosseira nos intervalos de 90 e de 185 dias. Na escala completa, os 7.597.961 retratos de treino geraram 48.083.205 linhas pessoa-período;

i) **pesos de treino e calibração**: em testes preliminares na menor escala do projeto (4% dos discos que falham e 0,4% dos demais), treinar com os pesos completos fez o modelo atingir sua melhor iteração após cerca de 30 iterações, porque um dia saudável pesava dezenas de vezes mais que um dia de falha. Por isso, os pesos de treino foram elevados ao expoente 0,5, heurística inspirada na ponderação atenuada de Sugiyama *et al.* (2007), sem a garantia teórica que esses autores estabelecem para outro contexto; os expoentes 0,75 e 1,0 foram avaliados como análise de sensibilidade, e não para escolher o expoente. Como a atenuação distorce a escala das probabilidades, cada intervalo recebeu uma recalibração de Platt de dois parâmetros (NICULESCU-MIZIL; CARUANA, 2005), ajustada com os pesos amostrais completos em metade dos discos de validação; a outra metade foi usada apenas para a parada antecipada do treino. Os hiperparâmetros principais foram taxa de aprendizado de 0,03, 31 folhas por árvore, no mínimo 200 amostras por folha, subamostragem de 80% das linhas e das variáveis por árvore e limite de 2.000 iterações, com parada antecipada após 100 iterações sem melhora na perda de validação; a melhor iteração do modelo principal foi a 419;

j) **previsão e avaliação (predict, evaluate)**: aplicação de todos os modelos aos discos de validação e teste e cálculo das métricas descritas ao fim desta seção;

k) **relatório (report)**: geração automática das tabelas usadas no capítulo 4.

O passo de amostragem, a fração de 10% de discos saudáveis, a janela diária de 90 dias, os sete intervalos, o agrupamento de modelos raros, o expoente dos pesos e os hiperparâmetros foram fixados de antemão, por custo computacional, e não ajustados por validação; além disso, cada modelo foi treinado uma única vez, com semente fixa. O efeito dessas escolhas sobre os resultados não foi medido, exceto o do expoente (seção 4.6).

**Tabela 1 – Composição da coorte por conjunto e estrato**

| Conjunto | Discos que falham em algum momento | Demais discos (amostra de 10%) | Discos com falha visível no período do conjunto | Retratos |
|---|---|---|---|---|
| Treino | 17.880 | 24.450 | 12.220 | 7.597.961 |
| Validação | 2.566 | 3.431 | 1.772 | 1.077.429 |
| Teste | 1.784 | 7.198 | 1.784 | 825.321 |
| Total | 22.230 | 35.079 | 15.776 | 9.500.711 |

Fonte: Elaborado pelo autor com base em Backblaze (2026), no resumo da coorte e no relatório do portão de verificação.

A diferença entre a primeira e a terceira coluna decorre da divisão temporal: um disco de treino que falha em 2024 pertence ao estrato dos que falham, mas, para o treino, é uma observação censurada em 31 de dezembro de 2023. Dos 26.679 números de série com registro de falha no painel bruto, 22.230 estão na coorte; os demais 4.449 são SSD ou discos sem registros na janela de seu conjunto. Dezesseis discos da coorte (14 de treino, 1 de validação e 1 de teste) não geraram retrato, situação que o portão de verificação registra como aviso e atribui a discos com menos de sete linhas na janela de seu conjunto; por isso, o teste avaliado tem 8.981 discos, e não 8.982.

Para isolar o efeito dos atributos SMART, foram treinados os modelos apresentados no Quadro 2. Todos usam o mesmo algoritmo, os mesmos retratos e os mesmos hiperparâmetros, com uma exceção: o modelo apenas com contexto, que tem só cinco variáveis, usa todas elas em cada árvore (fração de variáveis 1,0 em vez de 0,8). A tolerância da parada antecipada é de 100 iterações sem melhora no modelo principal e no modelo apenas com contexto e, para reduzir o tempo de treino, menor nos demais (60 iterações no classificador, 40 no modelo sem contadores críticos, 30 no de contexto com uso e 20 nos de expoente 0,75 e 1,0); na versão anterior do *pipeline*, executada com as duas configurações, essa redução não alterou a melhor iteração de nenhum modelo. A verificação não foi repetida na execução que origina os resultados, de modo que, nela, os modelos não foram comparados sob regra de parada idêntica.

**Quadro 2 – Modelos comparados**

| Modelo | Variáveis ou definição | Pergunta que responde |
|---|---|---|
| Sobrevivência, SMART + contexto | todas as 64 variáveis | modelo principal |
| Sobrevivência, apenas contexto (sem SMART) | modelo, fabricante, capacidade, dias em serviço, indicador de início do painel | o que se prevê sem SMART |
| Sobrevivência sem contadores críticos | todas, exceto os atributos 5, 187, 188, 197 e 198 (brutos, normalizados e tendências) | quanto do ganho permanece sem os atributos da política de substituição |
| Sobrevivência, contexto + uso | contexto mais os contadores de uso 4, 9, 12, 193, 240, 241 e 242 | se o ganho vem apenas de medir idade e desgaste |
| Sobrevivência com expoente 0,75 | variáveis do modelo principal; pesos de treino elevados a 0,75 | sensibilidade ao expoente dos pesos de treino |
| Sobrevivência com expoente 1,0 | variáveis do modelo principal; pesos amostrais completos no treino | sensibilidade ao expoente dos pesos de treino |
| Sobrevivência recalibrada no último ano | árvores do modelo principal, recalibradas só com 2023 | se uma recalibração recente corrige a perda de calibração |
| Classificador de 30 dias | variáveis do modelo principal; rótulo "falha em até 30 dias" | se o modelo de sobrevivência perde discriminação em relação a um classificador dedicado |
| Regra dos contadores críticos | soma de log(1 + x) dos valores brutos de 5, 187, 197 e 198, sem treino | desempenho de uma heurística simples baseada nos contadores de setores e de erros não corrigidos |

Fonte: Elaborado pelo autor (2026).

A regra dos contadores críticos é uma heurística construída para este estudo, e não a regra de substituição efetivamente aplicada pelo operador. Ela exclui o atributo 188 porque, na execução preliminar de 24 de outubro de 2026, os valores compactados desse atributo nos discos Seagate consumiam 89% de seu orçamento de falsos alarmes. Pelo mesmo motivo, os contadores críticos usados na regra e na definição de falha silenciosa são os atributos 5, 187, 197 e 198, enquanto a ablação sem contadores críticos retira também o 188.

A avaliação usou apenas os discos de teste, observados em 2024 e 2025, e todas as métricas foram ponderadas pelos pesos amostrais. A unidade de análise é o retrato (um disco em um dia), salvo indicação em contrário. Foram calculadas:

a) **discriminação por horizonte**: ROC-AUC e PR-AUC para falha em até 7, 30, 90, 180 e 365 dias. A PR-AUC foi incluída porque a falha é rara (SAITO; REHMSMEIER, 2015) e é estimada pela precisão média (*average precision*), soma em degraus da precisão ponderada pelos acréscimos de revocação. O estimador principal usa os retratos cuja situação no horizonte é conhecida: positivos são os que falham dentro do horizonte, e negativos, os observados em operação até o fim dele; os demais são descartados. Esse estimador mantém positivos de retratos próximos ao fim do painel, cujos negativos correspondentes são descartados, e por isso superestima a proporção de positivos nos horizontes longos; não atende, portanto, à recomendação de Xu *et al.* (2026). Por essa razão, calculou-se também uma variante IPCW, que repondera os retratos de situação conhecida pelo inverso da probabilidade de não terem sido censurados, estimada por Kaplan-Meier sem covariáveis (VOCK *et al.*, 2016); ela é válida sob censura independente, hipótese que a censura administrativa pode violar (KVAMME; BORGAN, 2023). Calculou-se ainda uma variante com um retrato sorteado por disco, ponderada pelo peso do disco. Em cada horizonte, o sorteio ocorre entre os retratos amostrados, que são mais densos perto da falha, depois de excluídos os de situação desconhecida. A estimativa pontual é a média de 20 sorteios; cada reamostragem do intervalo usa um único sorteio por disco, de modo que o intervalo incorpora essa variabilidade e não corresponde exatamente ao procedimento da estimativa pontual;

b) **concordância**: estatísticas C de Harrell e de Uno (HARRELL *et al.*, 1982; UNO *et al.*, 2011) entre o escore de risco (o negativo do número esperado de dias operacionais) e o tempo até a falha. A estatística C de Harrell usa os tempos observados sem truncamento; a de Uno restringe a contribuição dos eventos às falhas anteriores a 365 dias. Um par de retratos é comparável quando o de menor tempo é uma falha, inclusive pares de retratos do mesmo disco, e a ponderação de Uno usa a mesma estimativa de censura sem covariáveis. Por custo computacional, o cálculo usa uma amostra de 299.930 retratos de 3.267 discos inteiros;

c) **recortes**: positivos com pelo menos 7 dias de antecedência (os retratos dos últimos dias podem já refletir o defeito que motivou a retirada), falhas silenciosas (discos que falham sem nenhum dos contadores 5, 187, 197 e 198 acima de zero em qualquer retrato de teste), fabricante e capacidade. Os recortes de antecedência e de falhas silenciosas restringem apenas os positivos e mantêm todos os negativos, de modo que não equivalem ao desempenho em uma subpopulação identificável de antemão; os de fabricante e capacidade restringem positivos e negativos;

d) **alerta antecipado**: limiares definidos na metade de calibração dos discos de validação para que 0,1%, 0,3% ou 1% dos retratos saudáveis gerem alerta (orçamento de falsos alarmes). Retrato saudável é o de um disco observado em operação nos 30 dias seguintes; um alerta dado a um disco que falha depois desse prazo conta, portanto, como falso alarme. Alertas cujo desfecho em 30 dias é desconhecido, porque o painel termina ou o disco é retirado antes, ficam fora da precisão. O orçamento de 1% segue Han *et al.* (2023), e o de 0,1% corresponde ao ponto de operação de Xu *et al.* (2018). No teste, mediram-se a taxa de falsos alarmes, a precisão, a revocação por retrato, a proporção de discos que falham e recebem ao menos um alerta nos dias 0 a 29 antes da falha, incluído o dia da falha, e a proporção dos que recebem alerta com 7 dias ou mais de antecedência;

e) **calibração**: probabilidade prevista média contra a proporção observada, estimada por Kaplan-Meier para acomodar a censura, por decil de risco; razão entre risco previsto e observado em 30 dias por ano de calendário; e escore de Brier nos retratos de situação conhecida, comparado ao de uma previsão constante igual à proporção de positivos;

f) **vida útil remanescente**: entre os retratos cujo dia previsto para 10%, 50% ou 90% de probabilidade de falha cai dentro de um ano e cujo desfecho até esse dia é conhecido, a proporção que de fato falhou até esse dia; e, entre os retratos de discos que falham em até um ano, a proporção com mediana prevista dentro de um ano e a proporção em que o dia real da falha fica entre os dias previstos para 10% e 90%. A primeira medida descarta os retratos censurados antes do dia previsto, o que favorece os retratos com dia previsto próximo; por isso, foi calculada também com ponderação IPCW, em que cada falha conhecida é ponderada pelo inverso da probabilidade de permanecer sem censura até o dia da falha, e cada sobrevivente conhecido, até a véspera do dia previsto, com uma única curva de Kaplan-Meier do tempo de censura. Essa ponderação supõe que a censura independe tanto do tempo de falha quanto do dia previsto, o que é apenas aproximado, pois a maior parte da censura decorre do fim do painel e depende da data do retrato. As duas últimas medidas são condicionadas à ocorrência da falha, e nenhuma tem intervalo de confiança, de modo que são descritivas;

g) **retirada de discos**: comparação do risco previsto entre discos sem falha que deixam o painel até o fim do ano seguinte e discos que permanecem, como diagnóstico da hipótese de censura independente.

Os intervalos de confiança de 95% são intervalos percentílicos de um *bootstrap* por disco, com 200 reamostragens (50 para as estatísticas de concordância): reamostram-se discos inteiros, e não linhas, porque os retratos de um mesmo disco são correlacionados (PANG *et al.*, 2023). Nas métricas de discriminação e de alerta, a reamostragem é estratificada como a amostra; na razão entre risco previsto e observado por ano, não é estratificada. As diferenças entre modelos foram calculadas de forma pareada nas mesmas reamostragens. Os intervalos são condicionais aos modelos treinados, à recalibração, aos limiares de alerta e à estimativa de censura, que não foram refeitos a cada reamostragem, e não capturam a correlação entre discos de um mesmo servidor ou de um mesmo dia; por isso, podem subestimar a incerteza total.

# 4 RESULTADOS DA ANÁLISE E RECOMENDAÇÕES

Os resultados a seguir referem-se à execução completa de 9 de novembro de 2026. O conjunto de teste reúne 8.981 discos nunca vistos no treino, observados em 2024 e 2025, dos quais 1.784 falharam, em 825.321 retratos. No portão de verificação, 55 das 56 verificações foram aprovadas e uma emitiu aviso, sem erro (os 16 discos sem retrato citados na seção 3.2). Os valores entre colchetes são intervalos de confiança de 95%. Na ROC-AUC, 0,5 corresponde a uma ordenação aleatória.

## 4.1 GANHO DOS ATRIBUTOS SMART

A Tabela 2 compara o modelo principal com o modelo sem SMART, com o modelo sem os contadores críticos e com a regra dos contadores críticos, em cada horizonte. A última coluna repete o modelo principal com o estimador IPCW.

**Tabela 2 – ROC-AUC por horizonte de previsão no conjunto de teste**

| Falha em até | Sem SMART | SMART + contexto | Ganho do SMART | Sem contadores críticos | Regra (5, 187, 197, 198) | SMART + contexto, IPCW |
|---|---|---|---|---|---|---|
| 7 dias | 0,603 | 0,905 [0,895; 0,914] | +0,302 [0,284; 0,316] | 0,799 | 0,853 | 0,905 |
| 30 dias | 0,603 | 0,877 [0,865; 0,886] | +0,273 [0,260; 0,291] | 0,770 | 0,823 | 0,876 |
| 90 dias | 0,609 | 0,843 [0,832; 0,855] | +0,234 [0,219; 0,253] | 0,745 | 0,786 | 0,842 |
| 180 dias | 0,606 | 0,813 [0,801; 0,825] | +0,207 [0,194; 0,221] | 0,720 | 0,755 | 0,809 |
| 365 dias | 0,585 | 0,787 [0,777; 0,801] | +0,203 [0,188; 0,219] | 0,712 | 0,722 | 0,775 |

Fonte: Elaborado pelo autor com base em Backblaze (2026). O ganho é a diferença pareada entre o modelo com SMART e o modelo sem SMART, calculada antes do arredondamento.

Verifica-se que os atributos SMART elevam a ROC-AUC em todos os horizontes, com intervalos de confiança que excluem zero. O modelo sem SMART, que conhece apenas as cinco variáveis de contexto, ordena pouco melhor que o acaso (0,58 a 0,61). O ganho é maior em 7 dias (+0,302) do que em um ano (+0,203); uma vez que os horizontes usam retratos diferentes (ver o parágrafo após a Figura 2), essa diferença não constitui tendência medida, e é compatível tanto com a degradação física quanto com a política de substituição descrita na seção 2.2. O modelo também supera a regra dos contadores críticos em todos os horizontes: a diferença pareada vai de +0,052 [0,045; 0,060] em 7 dias a +0,066 [0,057; 0,077] em 365 dias. A Figura 2 apresenta os mesmos resultados com os intervalos de confiança.

**Figura 2 – ROC-AUC por horizonte no conjunto de teste, com intervalos de confiança de 95%**

![ROC-AUC por horizonte](figures/figura-2-roc-auc.svg)

Fonte: Elaborado pelo autor com base em Backblaze (2026).

As linhas da Tabela 2 não são uma tendência medida sobre os mesmos retratos: cada horizonte usa um subconjunto diferente de retratos. Um horizonte de H dias exige H dias de acompanhamento para confirmar que o disco sobreviveu, de modo que os negativos do horizonte de 365 dias vêm apenas de retratos datados até 1º de janeiro de 2025, enquanto os positivos vêm de todo o período de teste. O estimador IPCW compensa essa assimetria sob a hipótese de censura independente e altera pouco a ROC-AUC: a maior diferença, calculada antes do arredondamento, é de 0,012, em 365 dias. Essa proximidade mede a sensibilidade numérica ao estimador, e não demonstra robustez a censura informativa. Com um retrato por disco, a ROC-AUC do modelo principal é de 0,862 [0,838; 0,886] em 30 dias.

A assimetria afeta mais as medidas que dependem da prevalência. A Tabela 3 compara a proporção de positivos entre os retratos de situação conhecida com o risco observado por Kaplan-Meier e apresenta a precisão média do modelo principal nos dois estimadores.

**Tabela 3 – Raridade do evento e precisão média do modelo principal, por horizonte e por estimador**

| Falha em até | Positivos entre os retratos de situação conhecida | Risco observado, Kaplan-Meier (retratos de 2024) | Risco observado, Kaplan-Meier (retratos de 2025) | PR-AUC, situação conhecida | PR-AUC, IPCW |
|---|---|---|---|---|---|
| 7 dias | 0,027% | 0,030% | 0,023% | 0,0650 [0,0534; 0,0816] | 0,0646 [0,0532; 0,0811] |
| 30 dias | 0,121% | 0,133% | 0,103% | 0,1235 [0,1053; 0,1466] | 0,1206 [0,1027; 0,1434] |
| 90 dias | 0,388% | 0,403% | 0,314% | 0,1821 [0,1582; 0,2103] | 0,1700 [0,1474; 0,1979] |
| 180 dias | 0,865% | 0,808% | 0,631% | 0,2194 [0,1957; 0,2474] | 0,1892 [0,1674; 0,2162] |
| 365 dias | 2,272% | 1,562% | 1,085% | 0,3117 [0,2888; 0,3389] | 0,2292 [0,2066; 0,2576] |

Fonte: Elaborado pelo autor com base em Backblaze (2026). Nos retratos de 2025, o acompanhamento disponível é inferior a 180 dias para cerca de metade dos retratos e inferior a 365 dias para quase todos, de modo que os riscos desses horizontes dependem dos retratos do início do ano e são apenas indicativos.

Até 90 dias, a proporção de positivos entre os retratos de situação conhecida fica entre os riscos observados nos dois anos, e os dois estimadores de PR-AUC diferem pouco. Em 180 dias, essa proporção já supera os dois riscos observados; em 365 dias, chega a 2,272%, contra 1,562% em 2024 e 1,085% em 2025, e a PR-AUC cai de 0,3117 para 0,2292 com o estimador IPCW. Por isso, as conclusões deste relatório apoiam-se nos horizontes de até 90 dias, e os valores de 180 e 365 dias obtidos com o estimador de situação conhecida devem ser lidos como otimistas.

A raridade do evento limita a precisão alcançável: apenas 0,027% dos retratos antecedem uma falha em até 7 dias. A PR-AUC do modelo principal nesse horizonte é de 0,0650, cerca de 240 vezes a de uma ordenação aleatória, que seria próxima da proporção de positivos.

## 4.2 POLÍTICA DE SUBSTITUIÇÃO, USO E FALHAS SILENCIOSAS

A Tabela 4 detalha o resultado em 30 dias. Retirados os atributos 5, 187, 188, 197 e 198, que a Backblaze usa para decidir substituições, o modelo ainda atinge ROC-AUC de 0,770 [0,758; 0,784], e o modelo completo fica à frente por +0,106 [0,098; 0,114]. Em termos de diferença de ROC-AUC, cerca de 61% do ganho do SMART sobre o modelo sem SMART (0,167 de 0,273) permanece sem esses contadores. Essa proporção é uma razão entre estimativas pontuais, sem intervalo de confiança, e descreve a sensibilidade do resultado à retirada dessas variáveis, e não a parcela do ganho devida à política do operador, por dois motivos: os contadores retirados também registram degradação física, e os atributos mantidos podem carregar parte da mesma informação, como a contagem de eventos de realocação (atributo 196). Com os rótulos disponíveis, o efeito da política de substituição não pode ser estimado; a ablação mostra apenas que o ganho não depende exclusivamente dos cinco contadores. Os contadores de uso (idade, ciclos e volume lido e gravado) acrescentam pouco ao contexto: o modelo de contexto com uso atinge 0,654, e o modelo completo o supera em +0,222 [0,211; 0,236].

**Tabela 4 – ROC-AUC em 30 dias por modelo e por recorte do conjunto de teste**

| Recorte | Discos que falham | SMART + contexto | Sem SMART | Regra (5, 187, 197, 198) |
|---|---|---|---|---|
| Todos os retratos | 1.784 | 0,877 [0,865; 0,886] | 0,603 | 0,823 |
| Positivos com 7 ou mais dias de antecedência | 1.755 | 0,868 [0,855; 0,877] | 0,604 | 0,814 |
| Falhas silenciosas | 368 | 0,638 [0,608; 0,666] | 0,562 | 0,473 |
| Falhas com contador crítico acima de zero | 1.416 | 0,939 [0,932; 0,945] | 0,614 | 0,915 |
| Fabricante HGST | 380 | 0,931 [0,916; 0,947] | 0,599 | 0,888 |
| Fabricante Seagate | 764 | 0,897 [0,882; 0,910] | 0,618 | 0,852 |
| Fabricante Toshiba | 485 | 0,779 [0,752; 0,804] | 0,515 | 0,740 |
| Fabricante WDC | 155 | 0,826 [0,784; 0,874] | 0,527 | 0,785 |
| Capacidade de 16 TB ou mais | 530 | 0,814 [0,792; 0,835] | 0,585 | 0,754 |
| Capacidade abaixo de 16 TB | 1.254 | 0,902 [0,890; 0,912] | 0,528 | 0,850 |

Fonte: Elaborado pelo autor com base em Backblaze (2026). Nas linhas 2 a 4, apenas os positivos são restritos, e todos os negativos são mantidos; nas linhas de fabricante e capacidade, positivos e negativos pertencem ao recorte.

Dos 1.784 discos que falharam no teste, 368 (20,6%) são falhas silenciosas: nenhum dos contadores 5, 187, 197 e 198 ficou acima de zero em seus retratos de teste. Quando apenas esses discos contam como positivos, a ROC-AUC do modelo cai para 0,638, ainda acima do acaso, e sua PR-AUC é de 0,0007, para uma proporção de positivos de 0,025%. O valor da regra nesse recorte (0,473) decorre da própria seleção, e não mede desempenho: todos os positivos têm escore zero e empatam com os negativos sem contagem. A proporção de falhas silenciosas é próxima dos 23,3% relatados por Klein (2016) para a Backblaze, que usou definição semelhante com cinco atributos (incluindo o 188), e inferior aos mais de 56% observados por Pinheiro *et al.* (2007) na Google com quatro sinais semelhantes. As definições de falha silenciosa não são idênticas e as populações diferem em idade e geração de discos, de modo que a comparação é apenas indicativa.

Ao excluir dos positivos os retratos dos últimos 7 dias antes da falha, a ROC-AUC em 30 dias quase não muda (0,868), e a PR-AUC passa de 0,1235 para 0,0784 [0,0654; 0,0964]. Essa queda combina dois efeitos que a comparação não separa: a exclusão reduz a proporção de positivos de 0,121% para 0,093%, da qual a precisão média depende, e retira os retratos em que os contadores podem já refletir o defeito que motivou a substituição.

Entre fabricantes, a ROC-AUC varia de 0,779 (Toshiba) a 0,931 (HGST), e o intervalo da WDC, com apenas 155 discos que falham, é largo. Discos de 16 TB ou mais são ordenados pior que os menores (0,814 contra 0,902, com intervalos disjuntos). Segundo a documentação do projeto, esses discos correspondem a cerca de 10% do peso do treino e a 50% do peso do teste, o que indica mudança na composição da frota entre os períodos.

## 4.3 ALERTA ANTECIPADO

A Tabela 5 traduz o modelo em regras de alerta. O limiar de cada orçamento foi fixado nos discos de validação; no teste, mede-se quantos discos que falharam receberam ao menos um alerta nos dias 0 a 29 antes da falha e quantos retratos alertados eram verdadeiros.

**Tabela 5 – Desempenho dos alertas no conjunto de teste, por orçamento de falsos alarmes**

| Orçamento | Modelo | Falsos alarmes no teste | Precisão | Revocação por retrato | Discos que falham alertados | Alertados com 7 ou mais dias de antecedência |
|---|---|---|---|---|---|---|
| 0,1% | SMART + contexto | 0,21% [0,16; 0,25] | 15,3% [12,8; 18,4] | 30,6% [29,0; 32,6] | 1.020 (57%) | 763 (43%) |
| 0,1% | Regra | 0,48% [0,35; 0,58] | 5,9% [4,8; 7,8] | 24,6% [23,1; 26,5] | 664 (37%) | 500 (28%) |
| 0,3% | SMART + contexto | 0,57% [0,48; 0,66] | 8,7% [7,6; 10,4] | 45,1% [43,4; 47,0] | 1.246 (70%) | 1.015 (57%) |
| 0,3% | Regra | 0,79% [0,62; 0,92] | 4,8% [4,1; 6,2] | 33,1% [31,6; 35,2] | 839 (47%) | 664 (37%) |
| 1% | SMART + contexto | 1,87% [1,64; 2,07] | 3,8% [3,4; 4,4] | 61,3% [59,1; 63,2] | 1.391 (78%) | 1.203 (67%) |
| 1% | Classificador de 30 dias | 2,22% [1,99; 2,44] | 3,3% [3,0; 3,7] | 62,7% [60,6; 64,8] | 1.426 (80%) | 1.231 (69%) |
| 1% | Regra | 1,74% [1,48; 2,01] | 3,1% [2,7; 3,6] | 45,5% [43,2; 47,6] | 1.051 (59%) | 874 (49%) |
| 1% | Sem SMART | 2,55% [2,31; 2,87] | 0,3% [0,3; 0,4] | 7,0% [5,9; 8,3] | 141 (8%) | 135 (8%) |

Fonte: Elaborado pelo autor com base em Backblaze (2026). Falsos alarmes: proporção dos retratos saudáveis com alerta. Precisão: proporção dos retratos alertados, de desfecho conhecido, que antecedem uma falha em até 30 dias. Revocação por retrato: proporção dos retratos que antecedem uma falha em até 30 dias e recebem alerta. Discos alertados: de um total de 1.784.

Nos limiares do orçamento de 1%, o modelo alerta 340 discos a mais que a regra (1.391 contra 1.051) e 61,3% dos retratos que antecedem uma falha em até 30 dias, contra 45,5% da regra. A comparação é feita nos pontos de operação escolhidos na validação, cujas taxas de falsos alarmes no teste diferem (1,87% e 1,74%); não é, portanto, uma comparação à mesma taxa de falsos alarmes, ressalva que vale também para o classificador de 30 dias, que alerta 35 discos a mais que o modelo de sobrevivência com 2,22% de falsos alarmes. A vantagem do modelo sobre a regra não depende, porém, dessa diferença de taxas: no limiar do orçamento de 0,3%, o modelo alerta 1.246 discos com 0,57% de falsos alarmes no teste, mais que os 1.051 que a regra alerta no limiar do orçamento de 1%, com 1,74%. Como a contagem inclui o dia da falha, a proporção relevante para uma intervenção planejada é a de discos alertados com 7 dias ou mais de antecedência: 67% para o modelo e 49% para a regra. Discos que falham nas primeiras semanas de 2024 têm poucos retratos de teste antes da falha, o que reduz essas proporções.

A precisão de 3,8% equivale a cerca de 32 vezes a proporção de positivos de 0,121%, mas significa que a maioria dos retratos alertados não antecede uma falha em 30 dias. No limiar fixado na validação para o orçamento de 0,1%, cuja taxa de falsos alarmes no teste foi de 0,21%, a precisão sobe para 15,3%, e o modelo ainda alerta 57% dos discos que falham. Cerca de 6,5% dos alertas do orçamento de 1% têm desfecho desconhecido em 30 dias; contados como falsos, a precisão passa a 3,6%.

Duas ressalvas condicionam a leitura da Tabela 5. A primeira é que nenhum orçamento foi cumprido no teste: a taxa de falsos alarmes do modelo principal ficou em 0,21%, 0,57% e 1,87%, sempre com intervalo de confiança acima do valor fixado na validação. Os discos saudáveis do teste recebem escores mais altos que os da validação, o que se relaciona com a perda de calibração tratada na seção 4.5. A segunda é que precisão e falsos alarmes são medidos por retrato e em relação ao horizonte de 30 dias: um disco alertado por vários dias conta várias vezes, e um alerta dado mais de 30 dias antes da falha conta como falso. Essas medidas não equivalem, portanto, ao rendimento de substituir os discos alertados. A Figura 3 mostra a proporção de retratos de discos que falham com alerta, por distância até a falha.

**Figura 3 – Proporção de retratos de discos que falham com alerta, por dias até a falha (limiar do orçamento de 1%)**

![Alertas por dias até a falha](figures/figura-3-alertas.svg)

Fonte: Elaborado pelo autor com base em Backblaze (2026).

A proporção de retratos alertados cai de 69% na última semana antes da falha para 23% entre 180 e 364 dias antes. Entre 30 e 59 dias antes da falha, 49% dos retratos já recebem alerta, o que mostra que parte dos falsos alarmes da Tabela 5 recai sobre discos que falham depois do horizonte de 30 dias.

## 4.4 VIDA ÚTIL REMANESCENTE

Para cada retrato, o modelo informa o dia em que a probabilidade acumulada de falha atinge 10%, 50% (mediana da vida útil remanescente) e 90%. Entre os retratos de discos observados em operação durante todo o ano seguinte, a mediana prevista fica além de um ano em 99,9% dos casos. Entre os retratos de discos que falham em até um ano, o modelo indica mediana dentro do ano em 15,0%. A Tabela 6 mostra que essa proporção depende da distância até a falha.

**Tabela 6 – Retratos de discos que falham com mediana prevista dentro de um ano, por distância real até a falha**

| Dias reais até a falha | Retratos | Mediana prevista dentro de um ano |
|---|---|---|
| 0 a 6 | 11.632 | 47,5% |
| 7 a 13 | 11.720 | 38,5% |
| 14 a 29 | 26.982 | 32,5% |
| 30 a 59 | 48.813 | 24,9% |
| 60 a 89 | 46.454 | 19,1% |
| 90 a 179 | 18.146 | 12,5% |
| 180 a 364 | 25.961 | 6,9% |

Fonte: Elaborado pelo autor com base em Backblaze (2026). A coluna de retratos traz contagens não ponderadas; a amostragem é diária nos 90 dias anteriores à falha e semanal antes disso.

Constata-se que o modelo ajustado raramente atribui mais de 50% de probabilidade de falha em um ano a um disco que vem a falhar: mesmo na última semana, isso ocorre em menos da metade dos retratos. Esse resultado não demonstra ausência de sinal nos atributos SMART, pois um modelo calibrado pode atribuir probabilidade inferior a 50% a um disco que depois falha, e a discriminação em 180 e 365 dias é superior ao acaso nos dois estimadores (0,813 e 0,787 no estimador principal; 0,809 e 0,775 com ponderação IPCW, Tabela 2). Mostra, porém, que o modelo não fornece datas individuais de falha, em linha com a conclusão de Pinheiro *et al.* (2007) sobre modelos baseados somente em SMART.

Quando o modelo indica um dia dentro do ano, a proporção de retratos que falham até esse dia fica abaixo da nominal. Descartados os retratos sem desfecho conhecido, ela é de 7,0% até o dia previsto para 10% (113.802 retratos), 38,3% até a mediana prevista (45.249 retratos) e 82,5% até o dia previsto para 90% (7.981 retratos); com a ponderação IPCW, que compensa esse descarte sob a hipótese de censura independente, é de 6,0%, 33,7% e 79,8%. Os três valores se referem a conjuntos diferentes de retratos e não têm intervalo de confiança, a ponderação IPCW supõe que a censura independe do tempo de falha e do dia previsto, e nenhuma das duas estimativas corrige a retirada de discos relacionada à saúde, questionada na seção 4.5. Esses resultados indicam previsões pessimistas nos retratos avaliados, mas não estabelecem a magnitude da descalibração na população de retratos. O erro absoluto médio da mediana, nos 43.922 retratos de falha em que ela foi prevista dentro do ano, é de 110 dias, valor elevado para um horizonte máximo de 365 dias. Entre os retratos de discos que falham em até um ano, o dia real da falha fica entre os dias previstos para 10% e 90% em 25,4% dos casos; no cálculo, o limite inferior é arredondado para baixo e o superior para cima, em dias inteiros, e a faixa é aberta à direita quando o dia previsto para 90% fica além de um ano. Essa proporção é condicionada à falha observada em até um ano e, portanto, não tem 80% como referência nominal de cobertura. Ela descreve a inclusão das falhas observadas na faixa prevista, mas não permite avaliar a cobertura dessa faixa na população de retratos.

## 4.5 CALIBRAÇÃO, DERIVA E RETIRADA DE DISCOS

A Figura 4 compara, por decil de risco, a probabilidade prevista com a proporção observada por Kaplan-Meier.

**Figura 4 – Calibração por decil de risco no conjunto de teste, por horizonte (escalas logarítmicas)**

![Calibração por decil](figures/figura-4-calibracao.svg)

Fonte: Elaborado pelo autor com base em Backblaze (2026).

Os pontos acompanham a diagonal ao longo de três ordens de grandeza, mas com desvio sistemático. Do terceiro ao último decil, o previsto supera o observado em todos os horizontes; no decil de maior risco, em 1,6 a 1,8 vez (em 30 dias, 1,52% previsto contra 0,89% observado). Nos dois decis de menor risco, a partir de 90 dias, o observado supera o previsto, e o desvio cresce com o horizonte (em 365 dias, 0,38% observado contra 0,21% previsto no primeiro decil). Os decis não têm intervalo de confiança, e os desvios nos de menor risco, de valores absolutos muito pequenos, são apenas descritivos. Nos retratos de situação conhecida, a redução do escore de Brier em relação a uma previsão constante igual à proporção ponderada de positivos desse mesmo subconjunto foi de 4,2% em 30 dias e de 9,0% em 90 dias; em 7 dias, o escore foi 0,3% maior que o da constante. Essa comparação é descritiva, está sujeita à seleção pelo acompanhamento disponível e não separa calibração de discriminação.

A Tabela 7 mostra a razão entre o risco previsto e o observado em 30 dias, por ano. Os discos de validação pertencem ao período de treino: metade deles foi usada na recalibração, e a outra metade, na parada antecipada; a faixa de razões desses anos serve, portanto, de referência descritiva, e não de teste formal.

**Tabela 7 – Risco de falha em 30 dias previsto e observado, por conjunto e ano**

| Conjunto | Ano | Retratos | Observado | Previsto | Razão previsto/observado |
|---|---|---|---|---|---|
| Validação | 2016 | 70.518 | 0,162% | 0,183% | 1,13 [0,94; 1,37] |
| Validação | 2017 | 85.198 | 0,154% | 0,162% | 1,05 [0,86; 1,30] |
| Validação | 2018 | 102.268 | 0,134% | 0,127% | 0,95 [0,81; 1,10] |
| Validação | 2019 | 116.101 | 0,165% | 0,150% | 0,91 [0,72; 1,16] |
| Validação | 2020 | 137.012 | 0,084% | 0,116% | 1,38 [1,14; 1,73] |
| Validação | 2021 | 169.154 | 0,088% | 0,100% | 1,13 [0,98; 1,31] |
| Validação | 2022 | 191.823 | 0,109% | 0,127% | 1,17 [1,03; 1,34] |
| Validação | 2023 | 205.355 | 0,166% | 0,143% | 0,86 [0,77; 0,97] |
| Teste | 2024 | 422.201 | 0,133% | 0,157% | 1,18 [1,09; 1,28] |
| Teste | 2025 | 403.120 | 0,103% | 0,225% | 2,18 [1,89; 2,51] |

Fonte: Elaborado pelo autor com base em Backblaze (2026). Observado: estimativa de Kaplan-Meier. A razão foi calculada antes do arredondamento.

Nos anos de validação, a razão variou de 0,86 a 1,38, e em 2020, 2022 e 2023 o intervalo de confiança exclui 1: uma calibração única não acompanha a variação anual da taxa de falhas nem dentro do período de treino. Em 2024, a razão ficou dentro dessa faixa (1,18); em 2025, o modelo previu mais que o dobro das falhas observadas (2,18). A recalibração com dados de 2023 não reduziu o desvio: o modelo recalibrado obteve razões de 1,42 e 2,64. Entre os demais modelos, o modelo sem SMART teve as menores razões (1,07 e 1,66); o modelo de contexto com uso teve razões pouco menores que as do principal (1,16 e 2,03), e o classificador de 30 dias, maiores (1,34 e 2,82).

Trata-se de uma deterioração temporal da calibração, cuja causa a análise não identifica. Ela é compatível com a mudança na composição da frota (seção 4.2), com a deriva de conceito descrita na seção 2.3 (HAN *et al.*, 2023), na medida em que altere a relação entre atributos e falha, e com mudanças nos critérios de registro de falha ou de retirada de discos do operador.

A análise de retirada é um diagnóstico dessa última hipótese. Entre discos sem registro de falha, os que deixam o painel até o fim do ano seguinte tinham risco previsto médio de 0,88 a 3,17 vezes o dos que permanecem nos anos de validação (acima de 1 em sete dos oito anos), e 2,02 vezes em 2024 (509 discos retirados contra 5.809 mantidos). Essas razões não têm intervalo de confiança e usam o escore do próprio modelo; mostram uma associação entre retirada e escore previsto, que pode refletir idade, capacidade ou cronogramas de migração, e não apenas o estado do disco. A associação é compatível com censura informativa, mas não a demonstra. Se as retiradas removerem preferencialmente discos com maior risco latente de falha, o risco observado poderá ser inferior ao que ocorreria sem elas.

## 4.6 COMPARAÇÕES COMPLEMENTARES E SENSIBILIDADE

Em 30 dias, a diferença de ROC-AUC entre o modelo de sobrevivência e o classificador dedicado é de −0,001 [−0,004; 0,002], e a de PR-AUC, de +0,0053 [−0,0049; 0,0147]: nenhum dos dois ordena claramente melhor. Em uma execução anterior, que diferia desta apenas em 10 dos 7,6 milhões de retratos de treino, a ROC-AUC em 30 dias do modelo principal foi 0,002 menor, e a diferença de ROC-AUC entre os dois modelos foi de −0,006 [−0,009; −0,002]. Os intervalos por *bootstrap* cobrem a amostragem dos discos de teste, mas não a variação do treino, de modo que diferenças de poucos milésimos entre modelos devem ser lidas como empate. Na estatística C de Harrell sobre o risco em 30 dias, o classificador tem valor pontual maior (0,777 contra 0,771), sem intervalo para a diferença. A vantagem do modelo de sobrevivência está em fornecer, a partir de um único modelo, respostas coerentes para todos os horizontes, além de tratar a censura de forma explícita.

O expoente dos pesos de treino teve pouco efeito sobre a ordenação nesta escala, na qual os pesos menos atenuados não interromperam o treino tão cedo quanto nos testes preliminares (seção 3.2, item i): a melhor iteração foi a 213 com expoente 0,75 e a 191 com expoente 1,0, contra a 419 com 0,5, comparação sujeita à tolerância de parada menor desses dois modelos (seção 3.2). Em 30 dias, a ROC-AUC foi de 0,880 com expoente 0,75 e de 0,876 com 1,0, contra 0,877 com 0,5. O expoente 0,75 ficou à frente do 0,5 por 0,003 em 30 dias e por 0,005 em 90 dias, com intervalos que excluem zero ([0,0002; 0,0063] e [0,002; 0,008]), mas dentro da variação do treino descrita acima; os intervalos das diferenças entre os expoentes 1,0 e 0,5 incluem zero nos cinco horizontes. Na PR-AUC, o expoente 0,5 superou o 1,0 nos cinco horizontes, com intervalo acima de zero em todos, e teve valor pontual maior que o do 0,75 também nos cinco, com intervalo acima de zero apenas em 90 e 180 dias.

As estatísticas C de Harrell e de Uno do modelo principal são 0,762 [0,739; 0,779] e 0,756 [0,733; 0,774]. Os valores pontuais são próximos, mas as duas estatísticas diferem quanto à ponderação da censura e à restrição temporal dos eventos, de modo que essa comparação não isola a sensibilidade à censura.

Por fim, a importância por ganho do LightGBM, registrada nos metadados do modelo principal, concentra-se no início do intervalo de previsão (23%), no modelo do disco (11%), nos setores realocados, atributo 5 (11%), nos erros não corrigidos, atributo 187 (10%), nos setores pendentes, atributo 197 (10%), e no crescimento dos atributos 187 e 5 em 30 dias (4% cada); a capacidade responde por apenas 1,4%. Essa medida reflete o uso das variáveis nas árvores em conjunto e não permite inferir efeito causal. Os três atributos SMART de maior importância (5, 187 e 197) estão entre os que a Backblaze emprega para decidir substituições, o que reforça a ressalva de circularidade da seção 4.2.

## 4.7 RECOMENDAÇÕES

Com base nos resultados, recomenda-se aos operadores de *data centers*:

a) testar o modelo de sobrevivência com SMART e contexto em um piloto de priorização de inspeções, e não como decisão automática de substituição, visto que a maioria dos alertas não antecede uma falha em 30 dias;

b) escolher o limiar de alerta a partir do custo de cada intervenção, da perda evitada e da taxa de falsos alarmes medida em dados recentes, contando alertas por disco, e não por dia; os limiares avaliados neste relatório são exemplos, e suas taxas no teste (0,21% e 1,87%) superaram os orçamentos nominais (0,1% e 1%);

c) recalibrar as probabilidades e redefinir os limiares de alerta periodicamente, com dados recentes, e monitorar a razão entre falhas previstas e observadas;

d) não usar a estimativa de vida útil remanescente como data prevista de falha nem para planejamento de compras de longo prazo;

e) registrar separadamente falhas reativas e proativas e o motivo de cada retirada de disco, para permitir medir o poder preditivo do SMART sem a circularidade do rótulo;

f) coletar métricas de desempenho e de ambiente junto aos atributos SMART, que a literatura indica como complemento (LU *et al.*, 2020), a fim de investigar as falhas silenciosas.

Para trabalhos futuros, recomenda-se restringir a avaliação de cada horizonte aos retratos com acompanhamento possível completo, como recomendam Xu *et al.* (2026), tratar a retirada sem falha como evento concorrente, adotar avaliação com origem móvel (retreino periódico ao longo do tempo), medir os alertas por disco e escolher o expoente dos pesos por validação, como propõem Sugiyama *et al.* (2007).

# 5 CONSIDERAÇÕES FINAIS E LIMITAÇÕES DO ESTUDO

Este relatório teve como objetivo avaliar se os atributos SMART coletados pelo `smartctl` permitem estimar a probabilidade e o momento provável de falha de discos rígidos nos *data centers* da Backblaze. Conclui-se que o objetivo geral foi atingido, visto que a avaliação permitiu responder à questão proposta: os atributos SMART permitem ordenar os discos por risco com desempenho superior ao das informações de contexto, mas as probabilidades estimadas perderam calibração no período de teste, e o modelo não forneceu datas individuais de falha com precisão.

Quanto aos objetivos específicos, a formulação como análise de sobrevivência em tempo discreto com censura à direita (objetivo a) foi descrita no capítulo 3 e produziu, a partir de um único modelo, probabilidades para todos os horizontes e estimativas de vida útil remanescente. O ganho de discriminação dos atributos SMART sobre o modelo de contexto (objetivo b) foi mensurado na seção 4.1 e mostrou-se positivo em todos os horizontes. A ablação dos contadores usados pelo operador (objetivo c), apresentada na seção 4.2, mostrou que a maior parte do ganho permanece sem esses contadores, mas não permite estimar o efeito da política de substituição, e as falhas silenciosas continuam pouco previsíveis. O desempenho como sistema de alerta (objetivo d), apresentado na seção 4.3, mostrou que, nos pontos de operação avaliados, o modelo alerta mais discos que a regra dos contadores críticos, embora os orçamentos fixados na validação não tenham sido cumpridos no teste e a maioria dos alertas não anteceda uma falha no horizonte. A calibração e a estabilidade ao longo do tempo (objetivo e), tratadas nas seções 4.4 e 4.5, mostraram limitações na avaliação das estimativas de vida útil remanescente e perda de calibração no segundo ano de teste, não reduzida pela recalibração com dados do último ano anterior ao teste.

Como limitações, destacam-se:

a) **rótulo de falha**: a Backblaze decide parte das substituições com base nos mesmos atributos SMART usados pelo modelo, e o *dataset* não distingue falhas reativas de proativas; por isso, os resultados valem para as retiradas registradas por esse operador, e não para falhas físicas em geral, e o efeito da política de substituição não pôde ser estimado;

b) **amostra de um único operador**: os dados vêm de uma única carga de trabalho de armazenamento e de um único histórico de compras; não se testou a transferência do modelo para outro operador nem para computadores pessoais;

c) **estimador dos horizontes longos**: a avaliação principal usa os retratos de situação conhecida, que superestimam a proporção de positivos nos horizontes de 180 e 365 dias; a correção por ponderação depende da hipótese de censura independente, e a avaliação restrita aos retratos com acompanhamento completo não foi realizada;

d) **censura possivelmente informativa**: a análise de retirada mostra associação entre retirada e risco previsto, compatível com a violação da hipótese de censura independente; a retirada não foi modelada como evento concorrente;

e) **perda de calibração ao longo do tempo**: o modelo foi treinado uma única vez e avaliado em dois anos posteriores; não se realizou avaliação com origem móvel, a recalibração testada não reduziu o desvio e sua causa não foi identificada;

f) **unidade das métricas de alerta**: a precisão e a taxa de falsos alarmes foram medidas por dia de disco, e não por disco ou por intervenção, de modo que não equivalem à carga de trabalho de uma equipe de operação;

g) **escolhas fixadas**: o expoente dos pesos de treino, a fração de discos saudáveis amostrados, os intervalos de tempo e os hiperparâmetros foram fixados, e não ajustados por validação; a tolerância da parada antecipada difere entre os modelos, e seu efeito não foi verificado na execução deste relatório;

h) **intervalos de confiança**: o *bootstrap* por disco não captura a correlação entre discos de um mesmo servidor ou de um mesmo dia, de modo que os intervalos podem subestimar a incerteza total;

i) **variação do treino**: cada modelo foi treinado uma única vez, com semente fixa, e os intervalos de confiança não incluem a variação do treino; alterar 10 dos 7,6 milhões de retratos de treino mudou a ROC-AUC em 30 dias em 0,002, de modo que diferenças de poucos milésimos entre modelos não são conclusivas;

j) **semântica dos atributos**: o significado e a codificação dos atributos SMART variam entre fabricantes e modelos; modelos raros foram agrupados, e novos atributos exigiriam a mesma verificação de valores compactados.

# REFERÊNCIAS

AMRAM, M. *et al.* Interpretable predictive maintenance for hard drives. **Machine Learning with Applications**, Amsterdam, v. 5, 100042, 2021. DOI: https://doi.org/10.1016/j.mlwa.2021.100042.

BACKBLAZE. Backblaze Drive Stats for Q3 2025. **Backblaze Blog**, 11 nov. 2025. Disponível em: https://www.backblaze.com/blog/backblaze-drive-stats-for-q3-2025/. Acesso em: 9 nov. 2026.

BACKBLAZE. **Hard Drive Reliability & Test Data**. [*S. l.*]: Backblaze, 2026. Disponível em: https://www.backblaze.com/cloud-storage/resources/hard-drive-test-data. Acesso em: 9 nov. 2026.

BAIRAVASUNDARAM, L. N. *et al.* An analysis of latent sector errors in disk drives. *In*: ACM SIGMETRICS INTERNATIONAL CONFERENCE ON MEASUREMENT AND MODELING OF COMPUTER SYSTEMS, 2007, San Diego. **Proceedings** [...]. New York: ACM, 2007. p. 289-300. DOI: https://doi.org/10.1145/1254882.1254917.

BEACH, B. Hard drive SMART stats. **Backblaze Blog**, 12 nov. 2014. Disponível em: https://www.backblaze.com/blog/hard-drive-smart-stats/. Acesso em: 9 nov. 2026.

DOYLE, S. How the Backblaze Drive Stats dataset powers academic and AI/ML research. **Backblaze Blog**, 13 ago. 2026. Disponível em: https://www.backblaze.com/blog/backblaze-drive-stats-academic-ai-ml-research/. Acesso em: 25 out. 2026.

HAN, S. *et al.* StreamDFP: a general stream mining framework for adaptive disk failure prediction. **IEEE Transactions on Computers**, New York, v. 72, n. 2, p. 520-534, 2023. DOI: https://doi.org/10.1109/TC.2022.3160365.

HARRELL, F. E. *et al.* Evaluating the yield of medical tests. **JAMA**, Chicago, v. 247, n. 18, p. 2543-2546, 1982.

KAPOOR, S.; NARAYANAN, A. Leakage and the reproducibility crisis in machine-learning-based science. **Patterns**, Cambridge, v. 4, n. 9, 100804, 2023. DOI: https://doi.org/10.1016/j.patter.2023.100804.

KE, G. *et al.* LightGBM: a highly efficient gradient boosting decision tree. *In*: CONFERENCE ON NEURAL INFORMATION PROCESSING SYSTEMS, 31., 2017, Long Beach. **Advances in Neural Information Processing Systems 30**. Red Hook: Curran Associates, 2017. p. 3146-3154. Disponível em: https://proceedings.neurips.cc/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html. Acesso em: 9 nov. 2026.

KING, G.; ZENG, L. Logistic regression in rare events data. **Political Analysis**, Oxford, v. 9, n. 2, p. 137-163, 2001. DOI: https://doi.org/10.1093/oxfordjournals.pan.a004868.

KLEIN, A. What SMART stats tell us about hard drives. **Backblaze Blog**, 6 out. 2016. Disponível em: https://www.backblaze.com/blog/what-smart-stats-indicate-hard-drive-failures/. Acesso em: 25 out. 2026.

KLEIN, A. Backblaze Drive Stats for Q3 2024. **Backblaze Blog**, 12 nov. 2024. Disponível em: https://www.backblaze.com/blog/backblaze-drive-stats-for-q3-2024/. Acesso em: 9 nov. 2026.

KVAMME, H.; BORGAN, Ø. The Brier score under administrative censoring: problems and a solution. **Journal of Machine Learning Research**, [*S. l.*], v. 24, n. 2, p. 1-26, 2023. Disponível em: https://www.jmlr.org/papers/v24/19-1030.html. Acesso em: 9 nov. 2026.

LU, S. *et al.* Making disk failure predictions SMARTer! *In*: USENIX CONFERENCE ON FILE AND STORAGE TECHNOLOGIES, 18., 2020, Santa Clara. **Proceedings** [...]. Berkeley: USENIX Association, 2020. p. 151-167. Disponível em: https://www.usenix.org/conference/fast20/presentation/lu. Acesso em: 25 out. 2026.

MA, A. *et al.* RAIDShield: characterizing, monitoring, and proactively protecting against disk failures. *In*: USENIX CONFERENCE ON FILE AND STORAGE TECHNOLOGIES, 13., 2015, Santa Clara. **Proceedings** [...]. Berkeley: USENIX Association, 2015. p. 241-256. Disponível em: https://www.usenix.org/conference/fast15/technical-sessions/presentation/ma. Acesso em: 25 out. 2026.

MURRAY, J. F.; HUGHES, G. F.; KREUTZ-DELGADO, K. Machine learning methods for predicting failures in hard drives: a multiple-instance application. **Journal of Machine Learning Research**, [*S. l.*], v. 6, p. 783-816, 2005. Disponível em: https://jmlr.org/papers/v6/murray05a.html. Acesso em: 25 out. 2026.

NICULESCU-MIZIL, A.; CARUANA, R. Predicting good probabilities with supervised learning. *In*: INTERNATIONAL CONFERENCE ON MACHINE LEARNING, 22., 2005, Bonn. **Proceedings** [...]. New York: ACM, 2005. p. 625-632. DOI: https://doi.org/10.1145/1102351.1102430.

PANG, J. *et al.* Nonparametric bootstrap methods for interval estimation of the area under the ROC curve with correlated diagnostic test data: application to whole-virus ELISA testing in swine. **Frontiers in Veterinary Science**, Lausanne, v. 10, 1274786, 2023. DOI: https://doi.org/10.3389/fvets.2023.1274786.

PINHEIRO, E.; WEBER, W.-D.; BARROSO, L. A. Failure trends in a large disk drive population. *In*: USENIX CONFERENCE ON FILE AND STORAGE TECHNOLOGIES, 5., 2007, San Jose. **Proceedings** [...]. Berkeley: USENIX Association, 2007. p. 17-28. Disponível em: https://www.usenix.org/legacy/events/fast07/tech/pinheiro.html. Acesso em: 25 out. 2026.

SAITO, T.; REHMSMEIER, M. The precision-recall plot is more informative than the ROC plot when evaluating binary classifiers on imbalanced datasets. **PLoS ONE**, San Francisco, v. 10, n. 3, e0118432, 2015. DOI: https://doi.org/10.1371/journal.pone.0118432.

SCHROEDER, B.; GIBSON, G. A. Disk failures in the real world: what does an MTTF of 1,000,000 hours mean to you? *In*: USENIX CONFERENCE ON FILE AND STORAGE TECHNOLOGIES, 5., 2007, San Jose. **Proceedings** [...]. Berkeley: USENIX Association, 2007. p. 1-16. Disponível em: https://www.usenix.org/conference/fast-07/disk-failures-real-world-what-does-mttf-1000000-hours-mean-you. Acesso em: 25 out. 2026.

SIEMROTH, C.; PARK, Y. Are there manufacturer differences in hard-drive reliability? **IEEE Transactions on Cloud Computing**, New York, v. 14, n. 2, p. 1015-1024, 2026. DOI: https://doi.org/10.1109/TCC.2026.3679404.

SMARTMONTOOLS. **smartctl**: control and monitor utility for SMART disks. Versão 7.5. [*S. l.*]: smartmontools, 2025. Manual de referência smartctl(8) e banco de dados de unidades (drivedb.h). Disponível em: https://www.smartmontools.org/. Acesso em: 9 nov. 2026.

SUGIYAMA, M.; KRAULEDAT, M.; MÜLLER, K.-R. Covariate shift adaptation by importance weighted cross validation. **Journal of Machine Learning Research**, [*S. l.*], v. 8, p. 985-1005, 2007. Disponível em: https://www.jmlr.org/papers/v8/sugiyama07a.html. Acesso em: 25 out. 2026.

SURESH, K.; SEVERN, C.; GHOSH, D. Survival prediction models: an introduction to discrete-time modeling. **BMC Medical Research Methodology**, London, v. 22, 207, 2022. DOI: https://doi.org/10.1186/s12874-022-01679-6.

UNO, H. *et al.* On the C-statistics for evaluating overall adequacy of risk prediction procedures with censored survival data. **Statistics in Medicine**, Chichester, v. 30, n. 10, p. 1105-1117, 2011. DOI: https://doi.org/10.1002/sim.4154.

VAN DEN GOORBERGH, R. *et al.* The harm of class imbalance corrections for risk prediction models: illustration and simulation using logistic regression. **Journal of the American Medical Informatics Association**, Oxford, v. 29, n. 9, p. 1525-1534, 2022. DOI: https://doi.org/10.1093/jamia/ocac093.

VOCK, D. M. *et al.* Adapting machine learning techniques to censored time-to-event health record data: a general-purpose approach using inverse probability of censoring weighting. **Journal of Biomedical Informatics**, San Diego, v. 61, p. 119-131, 2016. DOI: https://doi.org/10.1016/j.jbi.2016.03.009.

XU, Y. *et al.* Improving service availability of cloud systems by predicting disk error. *In*: USENIX ANNUAL TECHNICAL CONFERENCE, 2018, Boston. **Proceedings** [...]. Berkeley: USENIX Association, 2018. p. 481-494. Disponível em: https://www.usenix.org/conference/atc18/presentation/xu-yong. Acesso em: 25 out. 2026.

XU, Y. *et al.* **Pitfalls of administrative censoring in survival models with time-indexed inputs**. arXiv:2607.10466, 2026. *Preprint*. Disponível em: https://arxiv.org/abs/2607.10466. Acesso em: 9 nov. 2026.

# APÊNDICE A – GUIA DE REPRODUÇÃO DOS RESULTADOS

Este apêndice descreve como reproduzir os resultados do capítulo 4 a partir do repositório do projeto. Dois pré-requisitos não acompanham o repositório: o painel consolidado e o executor *data-pipeline*.

a) **requisitos**: computador com Linux, Python 3.13 e o gerenciador *uv*; a escala completa exige ao menos 15 GiB de memória (a execução deste relatório usou 31 GiB; uma execução completa em 15 GiB atingiu pico de 11,0 GiB, com pouca folga);

b) **executor**: o *data-pipeline* é um projeto à parte, ainda sem repositório público, e deve estar no diretório vizinho ao do projeto (`../data-pipeline`); sem ele, é possível apenas inspecionar os resultados salvos em `results/`;

c) **dados**: os arquivos diários do Drive Stats de 2016 a 2025, obtidos na página da Backblaze (BACKBLAZE, 2026), devem ser consolidados em um único arquivo Parquet, colocado em `dataset/dataset.parquet`; o repositório não inclui o procedimento de consolidação, e a primeira etapa do *pipeline* só prossegue se o resumo SHA-256 do arquivo for igual ao registrado em `pipeline.toml`;

d) **instalação**: executar `uv sync` na raiz do projeto;

e) **escolha da escala**: em `config/sample.toml`, definir `scale = "full"` para reproduzir este relatório; as escalas `small` e `medium` estimam as mesmas grandezas com intervalos de confiança mais largos e exigem menos memória;

f) **verificação**: executar `uv run pytest` para os testes sobre um painel sintético e `uv run data-pipeline -n` para listar as etapas que seriam executadas;

g) **execução**: executar `uv run data-pipeline`; o progresso das etapas longas é registrado em `build/logs/`;

h) **resultados**: o relatório gerado fica em `build/report/` (`results.md` com os números e `analysis.md` com a explicação e as tabelas detalhadas); a cópia da execução usada neste relatório está em `results/full-2026-11-09-leakfix/`, e as das execuções anteriores citadas na seção 3.2, em `results/full-2026-10-24/`, `results/full-2026-10-27/` e `results/full-2026-10-30/`; a execução anterior citada na seção 4.6 está apenas no histórico do repositório;

i) **figuras deste relatório**: as Figuras 2 a 4 são geradas a partir dos arquivos de `results/full-2026-11-09-leakfix/` por `uv run python article/figures/figuras.py`.

As regras compartilhadas entre etapas (divisão dos conjuntos, intervalos de tempo, variáveis e parâmetros de avaliação) ficam em `config/study.toml`, e os hiperparâmetros de cada modelo, em `pipeline.toml`.
