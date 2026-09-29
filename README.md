# 🤖 Chollows: Assistent de Cholls i Notícies Tech per a Telegram

Un sistema complet, autònom i **100% GRATUÏT (sense cap cost mensual ni necessitat de contractar servidors)** que rastreja ofertes de productes i notícies tecnològiques cada matí a les **07:00 (hora local CET/CEST)** i te les envia directament al teu xat de Telegram.

L'assistent és completament interactiu: pots parlar-li en llenguatge natural per afegir productes, establir preus màxims, canviar-los o consultar què està seguint. Tu no toques mai cap fitxer de configuració ni base de dades a mà.

---

## 🏗️ Arquitectura del Sistema

```mermaid
flowchart TD
    User([👤 Usuari Telegram]) <-->|Xat interactiu / Comandes| Bot[🤖 bot.py]
    Bot <-->|Persistència automàtica| DB[(💾 SQLite data/data.db)]
    
    subgraph GitHub Actions [⚙️ GitHub Actions (100% Gratuït)]
        Cron[⏰ Cron 07:00 CET/CEST] --> Watch[🔍 watch.py]
        Drain[⏱️ Cron / Poll Drenatge] --> Bot
    end
    
    Watch -->|Llegeix productes| DB
    Watch --> Gemini[✨ Gemini API Flash / Fallback Estàtic]
    
    subgraph Connectors Modulars [🌐 Connectors de Cerca]
        Wallapop[📦 Wallapop: wallapy + Fallback Indexat]
        Chollometro[🔥 Chollometro / Dealabs RSS]
        Stores[🛒 Botigues Online: Amazon, PcComponentes]
        Alerts[📡 Google Alerts & Web Deals]
        News[📰 Google News / Bing RSS Tech en català]
    end
    
    Watch --> Connectors
    Watch -->|Deduplicació i formateig HTML| DB
    Watch -->|Envia Report Matinal| User
```

---

## 🌟 Característiques Principals

1. **Interacció Guiada per Telegram**:
   - Diàleg pas a pas: digues *"vull seguir un producte"* i el bot et demana el nom del producte i el preu màxim.
   - Comandes ràpides: *"afegir iPhone 15 Pro 750€"*, *"treure PS5"*, *"canviar preu de PS5 a 350€"*, *"mostra què em segueixes"*.
   - Gestió de temes tech: *"afegir tema Intel·ligència Artificial"*, *"treure tema Ciberseguretat"*.

2. **Cerca Intel·ligent Multi-Nom (Gemini API Flash + Fallback Estàtic)**:
   - En afegir un producte (ex: *"iPhone 15 Pro"*), crida el model Flash de Google Gemini per generar automàticament sinònims, abreviatures, variants ortogràfiques i combinacions comercials.
   - **Persistència eficient**: La llista es guarda a la base de dades; així, cada matí es cerca amb totes les variants sense tornar a consumir quota d'API.
   - **Fallback resilient**: Si l'API de Gemini cau, no hi ha quota o falla la xarxa, s'activa un motor estàtic de regles i diccionari tecnològic que garanteix que el servei mai no s'aturi.

3. **Connectors Modulars Resilients**:
   - **Wallapop**: Integrat amb la llibreria `wallapy`, amb fallback d'API directa i un motor de cerca d'anuncis reals indexats amb ciutat i preu.
   - **Chollometro & Dealabs**: Rastreig dels canals RSS de la xarxa Pepper i cerca web de promocions comunitàries.
   - **Botigues Online (Amazon / PcComponentes)**: Monitorització de preus d'oferta reals.
   - **Google Alerts / Web Deals**: Captura de gangues publicades a la xarxa.
   - **Notícies Tech**: Agregador de Google News en català (`hl=ca`) i espanyol, amb backup a Bing News i deduplicació persistent respecte de dies anteriors.

4. **Zero Cost i Zero Servidors**:
   - Executat íntegrament a **GitHub Actions** (runners gratuïts per a repositoris públics o amb quota gratuïta mensual en privats).
   - Base de dades SQLite persistent que sobreviu automàticament entre execucions mitjançant *git auto-commit*.
   - Gestió del canvi horari CET/CEST (horari d'estiu i d'hivern de Madrid/Barcelona).

---

## 🚀 Guia Pas a Pas per Posar-ho en Marxa

### Pas 1: Crear el Bot de Telegram i obtenir les credencials
1. Obre Telegram i cerca l'usuari oficial **`@BotFather`**.
2. Envia-li `/newbot` i segueix les instruccions (posa-li un nom i un usuari que acabi en `bot`, per exemple `ElMeuCholloBot`).
3. Guarda el **Token d'accés** que et proporcionarà (format: `123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ`). Aquest serà el teu `TELEGRAM_TOKEN`.
4. Per conèixer el teu **Chat ID**:
   - Envia un missatge a **`@userinfobot`** o a **`@raw_data_bot`** a Telegram.
   - Copia el teu identificador numèric (ex: `123456789`). Aquest serà el teu `TELEGRAM_CHAT_ID`.

### Pas 2: Obtenir la clau de Gemini API (del teu pla Google AI Pro / Studio)
1. Entra a [Google AI Studio](https://aistudio.google.com/).
2. Inicia sessió amb el compte associat al teu pla Google AI Pro.
3. Fes clic a **Get API key** → **Create API key**.
4. Copia la clau generada. Aquesta serà la teva `GEMINI_API_KEY`.

### Pas 3: Configurar els Secrets al teu repositori de GitHub
El codi ja està inicialitzat i pujat al teu repositori: **[1Amolina1/chollows-bot](https://github.com/1Amolina1/chollows-bot)**.

Ara només cal que configuris els secrets necessaris:
1. Al teu repositori [1Amolina1/chollows-bot](https://github.com/1Amolina1/chollows-bot), ves a:
   **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.
4. Afegeix els següents tres secrets:
   - `TELEGRAM_TOKEN`: El token del teu bot de @BotFather.
   - `TELEGRAM_CHAT_ID`: El teu ID numèric de Telegram.
   - `GEMINI_API_KEY`: La teva clau d'API de Google Gemini.

### Pas 4: Habilitar permisos d'escriptura per al workflow
Com que la base de dades SQLite es manté persistent guardant els canvis al propi repositori:
1. Al teu repositori de GitHub, ves a:
   **Settings** → **Actions** → **General**.
2. Fes scroll fins a la secció **Workflow permissions**.
3. Selecciona **Read and write permissions**.
4. Fes clic a **Save**.

### Pas 5: Provar el sistema
- Per provar el **Report Matinal**:
  Ves a la pestanya **Actions** a GitHub → fes clic al workflow **"Report Matinal Chollows (07:00 CET/CEST)"** → fes clic a **Run workflow** (amb l'opció `force: true` marcada). Rebràs el report immediatament a Telegram!
- Per parlar amb el **Bot**:
  - Pots executar-lo en local quan vulguis configurar productes:
    ```bash
    export TELEGRAM_TOKEN="el_teu_token"
    export TELEGRAM_CHAT_ID="el_teu_chat_id"
    export GEMINI_API_KEY="la_teva_gemini_key"
    python bot.py
    ```
  - O pots deixar que el workflow automàtic de GitHub Actions (`.github/workflows/bot_poll.yml`) atengui els missatges acumulats periòdicament sense necessitat de tenir cap terminal encès.

---

## 💬 Guia de Conversa amb l'Assistent

Pots parlar amb el bot directament des de la teva aplicació de Telegram:

| Acció | Què li pots dir al bot | Resposta de l'assistent |
| :--- | :--- | :--- |
| **Afegir pas a pas** | *"vull seguir un producte"* o *"afegir"* | Et demana el nom, després el preu màxim i confirma el seguiment. |
| **Afegir en una sola frase** | *"afegir iPhone 15 Pro 750€"* | Genera les variants, guarda a SQLite i confirma directament. |
| **Consultar seguiment** | *"mostra què em segueixes"* o */llista* | Llista tots els productes, preus sostre, variants, ciutat Wallapop i temes tech. |
| **Canviar preu** | *"canviar preu de iPhone 15 Pro a 720€"* | Actualitza el preu màxim a la BD i et mostra la llista actualitzada. |
| **Deixar de seguir** | *"treure PlayStation 5"* o */treure PS5* | Elimina el producte de la cerca activa. |
| **Configurar ciutat Wallapop**| *"canviar ciutat a Girona"* o *"ciutat Barcelona"* | Configura la ciutat i les coordenades GPS (lat, lon) per filtrar anuncis. |
| **Consultar ciutat actual** | *"mostra ciutat"* o */ciutat* | Mostra la ciutat configurada i les coordenades associades. |
| **Afegir tema de notícies** | *"afegir tema Intel·ligència Artificial"* | Incorpora el tema al report matinal de notícies tech. |
| **Treure tema de notícies** | *"treure tema Ciberseguretat"* | Elimina el tema de la cerca de notícies. |
| **Forçar report immediat** | *"report ara"* | Executa tots els connectors i t'envia el resum al moment. |
| **Cancel·lar diàleg** | *"cancel·lar"* | Atura el formulari interactiu actual. |

---

## 🗄️ Base de Dades Inicial

La base de dades SQLite es troba a [`data/data.db`](file:///home/arnau/chollows/data/data.db) i s'inicialitza amb dades d'exemple que pots modificar parlant amb el bot:

- **Productes preconfigurats**:
  1. `iPhone 15 Pro` (màx: 750.00€) — Variants: *Apple iPhone 15 Pro, iPhone 15Pro, 15 Pro*
  2. `PlayStation 5` (màx: 380.00€) — Variants: *PS5, Sony PS5, PlayStation 5 Slim, PS5 Slim*
  3. `MacBook Air M2` (màx: 800.00€) — Variants: *Apple MacBook Air M2, MacBook Air, Macbook M2*
- **Temes tecnològics preconfigurats**:
  - `Intel·ligència Artificial`
  - `Apple`
  - `Ciberseguretat`

---

## ⚠️ Anàlisi Tècnica: Els 3 Punts Més Fràgils del Sistema

Com a enginyer de sistemes i scraping, he identificat els tres punts més sensibles de l'arquitectura i com s'han blindat en aquest projecte:

### 1. Mesures Antiscraping i Canvis d'API No Oficials (Wallapop i Botigues)
* **Com es pot trencar**: Plataformes com Wallapop o botigues com PcComponentes i Amazon no ofereixen APIs obertes públiques per a particulars. Fan servir sistemes de protecció perimetral com **Cloudflare Turnstile** o **DataDome**, que detecten les IPs dels centres de dades de GitHub Actions (Azure) i poden respondre amb errors `403 Forbidden` o reptes de Captcha. Així mateix, la llibreria `wallapy` pot quedar desactualitzada si Wallapop canvia els seus endpoints interns.
* **Com s'ha mitigat al codi**: Hem dissenyat una arquitectura de **fallbacks en cascada de 3 nivells**:
  1. Intent amb `wallapy` (la llibreria més especialitzada).
  2. Intent amb capçaleres de navegador rotatives contra l'API REST.
  3. **Fallback infalible per contingut indexat**: Si Wallapop bloqueja la IP, el connector rastreja anuncis reals de Wallapop indexats amb format de títol estructurat (`"<Títol> de Segunda mano por <Preu> EUR en <Ciutat> - Wallapop"`). Google no està bloquejat per Wallapop i permet extreure el preu, títol i enllaç funcional fins i tot quan la connexió directa falla. A més, cada connector està aïllat: si Wallapop fallés completament, Chollometro i la resta continuaran enviant ofertes.

### 2. Fluctuació i Jitter del Rellotge de GitHub Actions (Cron Delay)
* **Com es pot trencar**: Els planificadors de cron de GitHub Actions són de servei *best-effort*. A les hores en punt (com les 05:00 o 06:00 UTC), milers de repositoris mundials engeguen tasques i els runners compartits poden patir cues de fins a 15-45 minuts de retard. A més, el canvi estacional entre horari d'estiu (CEST, UTC+2) i d'hivern (CET, UTC+1) sol desquadrar les hores fixes dels crons habituals.
* **Com s'ha mitigat al codi**:
  - Hem programat el cron a les dues hores clau: `- cron: '0 5,6 * * *'`.
  - Dins de [`watch.py`](file:///home/arnau/chollows/watch.py), fem servir la biblioteca estàndard `zoneinfo` amb la zona horària `Europe/Madrid`. El codi valida si l'hora local són les `07:xx`. Si s'executa a l'hora que no toca, el procés s'atura netament sense duplicar missatges.
  - La comprovació d'hora contempla un marge ample per absorbir retards de càrrega dels servidors de GitHub.

### 3. Concurrència i Conflictes de Git sobre la Base de Dades SQLite
* **Com es pot trencar**: Com que no fem servir servidors de pagament, la persistència de dades es basa en fer un `git commit` i `git push` del fitxer [`data/data.db`](file:///home/arnau/chollows/data/data.db) en acabar el job. Si l'usuari interactua amb el bot al mateix minut que s'executa el report matinal, o si es fa un `git push` manual des del teu ordinador, GitHub Actions pot rebre un error `rejected (non-fast-forward)` per desincronització de branques.
* **Com s'ha mitigat al codi**:
  - Al workflow de GitHub Actions s'executa sempre `git pull --rebase origin main || true` just abans de fer el push.
  - A més, mantenim un fitxer JSON de seguretat [`data/initial_seed.json`](file:///home/arnau/chollows/data/initial_seed.json) de manera que l'estat crític sempre es pot recuperar de forma determinista.
