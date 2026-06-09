Il certificato SSL dell'EW-50E è **self-signed**: la verifica è disabilitata intenzionalmente.

### Comunicazione XML
Il sistema usa messaggi XML su WebSocket con tre tipi di comando:

| Comando | Direzione | Uso |
|---------|-----------|-----|
| `getRequest` | Client → Server | Richiesta dati |
| `getResponse` | Server → Client | Risposta a una richiesta |
| `notifyRequest` | Server → Client | Aggiornamento spontaneo (es. temperatura) |

### Auto-discovery gruppi
Al primo avvio viene inviata la richiesta:
```xml
<Packet>
  <Command>getRequest</Command>
  <DatabaseManager>
    <Mnet Group="all" Attribute="GroupName"/>
  </DatabaseManager>
</Packet>
```
L'EW-50E risponde con i nomi di tutti i gruppi configurati, che vengono usati per creare le entità in Home Assistant con i nomi corretti.

### Allarmi
Gli allarmi sono disponibili tramite tre meccanismi:
- `<SystemAlarm Alert="ON">` → allarme globale di sistema
- `<AlarmStatusList><AlarmStatusRecord>` → lista allarmi per gruppo
- `<RefUnit ErrorSign="ON">` → errori unità refrigeranti

---

## 🐛 Debug

Per verificare il protocollo WS direttamente dal browser, apri la console JS sull'interfaccia EW-50E e incolla:

```javascript
const OrigWS = WebSocket;
window.WebSocket = function(...a) {
  const ws = new OrigWS(...a);
  ws.addEventListener('message', e => console.log('WS MSG:', e.data));
  return ws;
};
```
Poi ricarica la pagina con **F5** — i messaggi XML appariranno in console.

Per i log di Home Assistant, cerca `custom_components.ew50e` nel log di sistema.

---

## 📋 Requisiti

- Home Assistant 2026.1 o superiore
- EW-50E / EW-C50E raggiungibile sulla rete locale
- Python `aiohttp >= 3.8.0` (installato automaticamente)

---

## 📄 Licenza

MIT License — vedi [LICENSE](LICENSE) per i dettagli.
