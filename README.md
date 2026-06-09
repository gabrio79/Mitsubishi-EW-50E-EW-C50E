# Mitsubishi Electric EW-50E / EW-C50E - Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/default)
[![Project Version](https://img.shields.io/badge/version-1.0.2-blue.svg?style=for-the-badge)](https://github.com/gabrio79/Mitsubishi-EW-50E-EW-C50E)
[![Home Assistant](https://img.shields.io/badge/Home_Assistant-Custom_Component-green.svg?style=for-the-badge)](https://www.home-assistant.io)

Integrazione custom nativa per **Mitsubishi Electric EW-50E / EW-C50E** (compatibile anche con i sistemi della famiglia AE-200E). Permette il monitoraggio centralizzato dello stato, delle temperature e delle anomalie di tutte le zone tramite Home Assistant.

---

## 🚀 Caratteristiche

- **Protocollo nativo**: Comunicazione in tempo reale tramite **WebSocket WSS** (porta 443) con parsing XML proprietario Mitsubishi
- **Auto-discovery gruppi**: I nomi delle zone vengono scaricati **automaticamente dall'EW-50E** al primo avvio — nessuna configurazione manuale
- **Autenticazione JWT**: Gestione sicura del token tramite login HTTP iniziale, poi passato al WebSocket
- **Aggiornamento automatico**: Sincronizzazione ogni 30 secondi tramite `DataUpdateCoordinator`
- **Configurazione UI**: Interamente configurabile tramite interfaccia grafica (Config Flow)
- **Resilienza**: Riconnessione automatica al WebSocket in caso di disconnessione

---

## 📊 Entità create

### Sensori globali
| Entità | Descrizione |
|--------|-------------|
| `sensor.ew_50e_temperatura_esterna` | Temperatura outdoor (°C) |
| `sensor.ew_50e_stato_sistema` | Stato M-NET (`NORMALE` / `ALLARME`) |
| `sensor.ew_50e_allarmi_attivi` | Numero allarmi attivi con dettaglio |
| `binary_sensor.ew_50e_anomalia_sistema` | `ON` se almeno un allarme è attivo |
| `binary_sensor.ew_50e_perdita_gas_refrigerante` | Allarme perdita gas refrigerante |

### Per ogni zona (auto-scoperta)
I sensori seguenti vengono creati automaticamente per **ogni gruppo configurato nell'EW-50E**, usando i nomi esatti impostati nel centralino:

| Entità | Descrizione |
|--------|-------------|
| `sensor.<nome_zona>_temperatura` | Temperatura ambiente rilevata (InletTemp) |
| `sensor.<nome_zona>_setpoint` | Temperatura impostata |
| `sensor.<nome_zona>_stato` | Stato operativo (`ON - COOL`, `OFF`, `ERRORE`) |
| `binary_sensor.<nome_zona>_anomalia` | `ON` se la zona è in errore |

---

## 📂 Struttura del Repository
