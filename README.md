# EW-50E Home Assistant Integration

Integrazione custom per **Mitsubishi Electric EW-50E / EW-C50E** (e famiglia AE-200E).

## Protocollo

- Comunicazione via **WebSocket WSS** (porta 443) con XML proprietario
- Autenticazione: **JWT token** ottenuto via HTTP login
- Aggiornamento: ogni **30 secondi** (configurabile)

## Struttura file

```
custom_components/ew50e/
├── __init__.py          ← Client WebSocket + Coordinator
├── manifest.json        ← Metadati integrazione
├── config_flow.py       ← Setup guidato da UI
├── strings.json         ← Testi interfaccia
├── sensor.py            ← Sensori temperatura e stato
└── binary_sensor.py     ← Sensori anomalie/allarmi
```

## Sensori creati

### Sensori globali
| Entità | Descrizione |
|---|---|
| `sensor.ew_50e_temperatura_esterna` | Temperatura outdoor (°C) |
| `sensor.ew_50e_stato_sistema` | Stato M-NET (NORMALE / ALLARME) |
| `sensor.ew_50e_allarmi_attivi` | Numero allarmi attivi |
| `binary_sensor.ew_50e_anomalia_sistema` | ON se c'è almeno un allarme |
| `binary_sensor.ew_50e_perdita_gas_refrigerante` | Allarme perdita refrigerante |

### Per ogni gruppo (17 zone)
| Entità | Descrizione |
|---|---|
| `sensor.<zona>_temperatura` | Temperatura ambiente (InletTemp) |
| `sensor.<zona>_setpoint` | Temperatura impostata |
| `sensor.<zona>_stato` | ON/OFF + modalità |
| `binary_sensor.<zona>_anomalia` | ON se la zona è in errore |

### Zone configurate
1. Farmacia - Magazzino
2. Farmacia - Cassetteria
3. Farmacia - Autoanalisi
4. Farmacia - Galenico
5. Farmacia - Bancone
6. Farmacia - Isola Centrale
7. Farmacia - Porta Automatica
8. Farmacia - MammaBambino
9. Casa - Soggiorno
10. Casa - Camera Greta
11. Casa - Camera Matrimoniale
12. Bilocale - Soggiorno
13. Studio 1 - Roggero
14. Studio 3
15. Studio 2 - Savernini
16. Studio 4 - Fisio
17. Studi - Sala Aspetto

## Installazione

### 1. Copia i file
```bash
cp -r custom_components/ew50e/ /config/custom_components/
```

### 2. Riavvia Home Assistant

### 3. Aggiungi l'integrazione
Vai su **Impostazioni → Dispositivi e servizi → Aggiungi integrazione**
Cerca **"Mitsubishi EW-50E"** e inserisci:
- **IP**: `192.168.50.72`
- **Username**: `initial` (o il tuo utente)
- **Password**: la password dell'interfaccia web

### 4. Aggiungi le automazioni
Incolla il contenuto di `automations_ew50e.yaml` nelle tue automazioni.

### 5. Aggiungi la dashboard
Vai su **Dashboard → Aggiungi vista → Editor YAML** e incolla `lovelace_dashboard.yaml`.

## Note tecniche

### Autenticazione
Il login avviene tramite GET su `https://<IP>/control/login?loginId=<user>&password=<pass>`.
La risposta contiene il **JWT token** usato per aprire il WebSocket su `wss://<IP>/b_xmlproc/?token=<JWT>`.

Il certificato SSL dell'EW-50E è **self-signed**: la verifica SSL è disabilitata intenzionalmente.

### Protocollo XML
Il sistema usa due tipi di comando:
- `getRequest` → richiesta dati (client → server)
- `getResponse` → risposta dati (server → client)
- `notifyRequest` → aggiornamento spontaneo (server → client, es. temperature in tempo reale)

### Allarmi
Gli allarmi sono disponibili in:
- `<SystemAlarm Alert="ON" ...>` → allarme di sistema globale
- `<Mnet><AlarmStatusList><AlarmStatusRecord ...>` → lista allarmi per gruppo
- `<RefUnit ErrorSign="ON" ErrorCode="..." ...>` → errori unità refrigeranti

### Debugging
Per verificare i dati ricevuti, apri la console JS sull'interfaccia EW-50E e lancia:
```javascript
const OrigWS = WebSocket;
window.WebSocket = function(...a) {
  const ws = new OrigWS(...a);
  ws.addEventListener('message', e => console.log('WS MSG:', e.data));
  return ws;
};
```
Poi ricarica la pagina con F5.
