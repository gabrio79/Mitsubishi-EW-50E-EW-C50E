# Changelog

Tutte le modifiche rilevanti a questo progetto sono documentate in questo file.
Il formato è basato su [Keep a Changelog](https://keepachangelog.com/it/1.1.0/) e il progetto adotta il [Semantic Versioning](https://semver.org/lang/it/).

## [2.1.0] - 2026-11-01

### Added
- **Architettura Multi-Dispositivo per Zona (18 Dispositivi):** separato il controller centrale (`EW50E`, con le sole 4 entità globali) dai **17 sotto-dispositivi di zona** (collegati via `via_device`), ciascuno contenente esclusivamente i propri 2 sensori (`Stato` e `Anomalia`).
- **Migrazione & Pulizia Automatica `entity_id`:** aggiunto in `__init__.py` il riallineamento automatico del `DeviceRegistry` e dell'`EntityRegistry` all'avvio che rimuove prefissi indesiderati di area/hub (es. `cortile_ew_50e_mitsubishi_`) garantendo ID puliti (`sensor.studio_2_savernini_stato`, `binary_sensor.studio_2_savernini_anomalia`, ecc.) senza dover eliminare e ri-aggiungere l'integrazione.
- **Dashboard Lovelace divisa per Macro-Zona (`dashboards/ew50e.yaml`):** sostituito l'elenco piatto con card **Anomalie attive** in cima + **4 card dedicate per Macro-Zona** (*Farmacia*, *Studi*, *Casa*, *Bilocale*) alimentate dagli attributi `macro_zona` e `nome_breve`.
- Aggiunti `dark_icon.png` e `dark_icon@2x.png` in `custom_components/ew50e/brand/` e URL assoluto `raw.githubusercontent.com` per il banner HACS in `README.md`.

---

## [2.0.0] - 2026-11-01

### Added
- **Nuovi Brand Asset Nativi Home Assistant con Logo Mitsubishi (`custom_components/ew50e/brand/`):** Creati `icon.png` (`256x256`), `icon@2x.png` (`512x512`), `logo.png` (`512x160`), `logo@2x.png` (`1024x320`), `dark_logo.png` (`512x160`) e `dark_logo@2x.png` (`1024x320`) in formato PNG RGBA trasparente con marchio Mitsubishi Electric (conformi a Home Assistant 2026.3+).
- **Hero Banner HACS & GitHub (`assets/`):** Creati `assets/hacs_banner.png` e `assets/github_social_preview.png` (`1280x640`) con lockup Mitsubishi Electric + badge `v2.0 • HACS` e integrati nell'intestazione del `README.md` con pulsante 1-click *My Home Assistant / HACS*.
- Aggiunto attributo `segnalazione_filtro` (`FilterSign`) sui sensori di stato zona per monitorare la manutenzione filtri senza generare falsi allarmi di guasto.
- Aggiunta cartella `custom_components/ew50e/translations/` con file di localizzazione `it.json` e `en.json` per il Config Flow.
- Aggiunto file `CHANGELOG.md` secondo lo standard Keep a Changelog / SemVer.
- Aggiunto `configuration_url` anche sul `DeviceInfo` dei `binary_sensor`.

### Changed
- **Riscrittura Major del Motore Protocollo WebSocket XML (`b_xmlproc`) — validata live su hardware EW-50E:**
  - Connessione WebSocket con subprotocollo `b_xmlproc`, header `Origin`, handshake iniziale `<SystemData MnetStatus="*" />`, coda sequenziale `getResponse` e rinnovo token su `/servlet/Update`.
  - Auto-discovery nativa dei gruppi e dei nomi (`GroupNameWeb`) tramite `<ControlGroup><MnetList /></ControlGroup>`, con ripristino automatico dei nomi completi quando troncati dal limite hardware di 20 caratteri dell'EW-50E.
  - Lettura stati M-NET batch con attributi espliciti wildcard (`Drive="*" Mode="*" ...`) al posto dell'attributo inesistente `Attribute="All"` (che causava stati `N/D`).
  - Lettura codici allarme tramite attributo `AlarmCode` in `AlarmStatusRecord` e query `SystemAlarm` con intestazione `POST /servlet/FreezerServlet HTTP/1.1`.
- **Config Flow (`config_flow.py`):** Unificato il test di connessione utilizzando direttamente `EW50EClient` con distinzione tra `invalid_auth` e `cannot_connect`.
- **Event Loop Async Safety:** Sostituita la chiamata bloccante `ssl.create_default_context()` con contesto leggero `ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)` e rimosso `async_timeout` a favore di `asyncio.timeout` nativo di Python 3.12+.
- **Disciplina Logging (Prevenzione saturazione log HA):** Ridotti a `DEBUG` i messaggi ripetitivi ad ogni ciclo di polling; mantenuto `INFO` solo alla prima connessione riuscita e al completamento dell'auto-discovery.
- **Manifest & HACS (`manifest.json`, `hacs.json`):** Rimossa chiave non valida `"type"` da `hacs.json`, allineata `iot_class` a `local_polling`, aggiunto `issue_tracker` e rimosse vecchie immagini stock duplicate dalla root e da `icons/`.

### Fixed
- Risolto bug critico per cui tutte le zone restavano bloccate in stato `N/D` e gli `AlarmCode` risultavano vuoti.
- Risolto stato `UNKNOWN` iniziale di `mnet_status` in assenza di allarmi di sistema.

---

## [1.18] - 2026-06-14

### Added
- Aggiunte icone ufficiali del brand in `custom_components/ew50e/brand/` (`icon.png`, `logo.png`).

### Fixed
- Migliorata gestione stato sistema e rimozione riferimenti personali hardcoded dal package YAML di esempio.

---

## [1.16] - 2026-06-13

### Changed
- Spostati `icon.png` e `logo.png` nella root e in `icons/` per la visibilità su HACS.
- Allineati gli `entity_id` di sistema (`sensor.ew50e_stato_sistema`, `binary_sensor.ew50e_anomalia_sistema`, `sensor.ew50e_allarmi_attivi`, `binary_sensor.ew50e_perdita_gas_refrigerante`).

---

## [1.15] - 2026-06-12

### Changed
- **Versione semplificata:** Rimossa la lettura e la creazione delle entità di temperatura e setpoint; l'integrazione monitora esclusivamente stati operativi (`ON - <Mode>`, `OFF`, `ERRORE`) e allarmi/anomalie di sistema e di zona.
- Aggiunto package `packages/ew50e_telegram.yaml` per notifiche Telegram (nuova anomalia, rientro, offline) e dashboard `dashboards/ew50e.yaml` (Mushroom + auto-entities).

