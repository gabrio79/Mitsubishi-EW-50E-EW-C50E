# Mitsubishi Electric EW-50E / EW-C50E - Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/default)
![Project Version](https://img.shields.io/badge/version-1.0.1-blue.svg?style=for-the-badge)
![Home Assistant](https://img.shields.io/badge/Home__Assistant-Custom__Component-green.svg?style=for-the-badge)

Integrazione custom nativa per **Mitsubishi Electric EW-50E / EW-C50E** (compatibile anche con i sistemi della famiglia AE-200E). Permette il monitoraggio centralizzato dello stato, delle temperature e delle anomalie di tutte le zone tramite Home Assistant.

## 🚀 Caratteristiche

- **Protocollo**: Comunicazione in tempo reale tramite **WebSocket WSS** (porta 443) con parsing XML nativo.
- **Autenticazione**: Gestione sicura del token JWT tramite login HTTP iniziale.
- **Aggiornamento**: Sincronizzazione automatica tramite `DataUpdateCoordinator` ogni 30 secondi.
- **Configurazione**: Interamente configurabile tramite interfaccia utente (UI Config Flow).
- **Integrità**: Gestione degli errori di connessione e avvisi in caso di anomalie di rete o di blocco del sistema M-NET.

---

## 📂 Struttura del Repository

Per garantire la conformità con i requisiti di validazione di HACS, il repository è strutturato come segue:

```text
Mitsubishi-EW-50E-EW-C50E/
├── custom_components/
│   └── ew50e/
│       ├── __init__.py          # Client WebSocket + DataUpdateCoordinator (17 zone)
│       ├── binary_sensor.py     # Sensori diagnostici, anomalie e perdite gas
│       ├── config_flow.py       # Interfaccia di configurazione guidata (UI)
│       ├── icon.png             # Icona quadrata del componente per la UI di HACS
│       ├── logo.png             # Logo orizzontale per la documentazione HACS
│       ├── manifest.json        # Metadati dell'integrazione e dipendenze
│       ├── sensor.py            # Sensori di temperatura (Inlet) e stato operativo
│       └── strings.json         # Traduzioni dei testi di configurazione
├── hacs.json                    # Configurazione metadati per HACS Store
└── README.md                    # Questa documentazione
