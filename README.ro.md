# 🌡️ HeatWise – încălzire inteligentă și hibridă pentru Home Assistant

[![Deschide Home Assistant și arată acest repository în HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=RazvanR1&repository=HeatWise&category=integration)
![Version](https://img.shields.io/badge/version-0.3.0-blue)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
![Local only](https://img.shields.io/badge/cloud-none-success)
[![Tests](https://github.com/RazvanR1/HeatWise/actions/workflows/tests.yml/badge.svg)](https://github.com/RazvanR1/HeatWise/actions/workflows/tests.yml)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-support-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/razvanr1)

**HeatWise conduce toată încălzirea ca pe un singur sistem și decide și _cu ce_ încălzește.** Multe
case au mai multe surse de căldură: centrală pe gaz, capete termostatice și aere condiționate care pot
încălzi. Într-o zi blândă HeatWise încălzește camerele cu AC-urile și lasă centrala să stea; când se
face frig sau gazul e mai ieftin, predă din nou centralei. Merge cu orice termostat, cap termostatic
sau AC pe care îl vede Home Assistant, și totul rulează local.

> 🇬🇧 [English version](README.md)

![Panoul HeatWise](docs/screenshots/panel-ro.png)

---

## Ce face

| | |
|---|---|
| 💸 **Alege sursa cea mai ieftină** | Îi dai prețul la gaz și la curent (valori fixe sau orice senzor de preț) și compară gazul cu eficiența AC-ului la temperatura de afară. Fără prețuri, comută la un prag de temperatură ales de tine. |
| ❄️ **Folosește AC-urile cum trebuie** | Reglează fiecare AC după senzorul din **cameră**, nu după termometrul AC-ului, și oprește doar aparatele pornite de el. Dacă cineva pornește sau oprește un AC de mână, HeatWise nu se atinge de el o vreme. |
| 🔥 **Ține centrala deoparte** | Cât încălzesc AC-urile, termostatul principal coboară la temperatura „plecat”, ca gazul și curentul să nu încălzească casa în același timp. Camerele cu capete termostatice pot cere căldură de la centrală sau pot copia termostatul principal. |
| 🏠 **Știe cine e acasă** | Confort cât e cineva acasă, temperatura „plecat” când casa e goală. Întârzierea pornește doar când cineva chiar pleacă. |
| 📅 **Urmează programul tău** | Orice ajutor Program (Schedule) sau input boolean: pornit = confort, oprit = eco. Camerele pot avea program propriu sau urmează casa. |
| ✋ **Respectă modificările manuale** | Schimbi un termostat de mână și modificarea rămâne cât timp alegi tu sau până la următorul pas din program. |
| 🪟 **Ferestre și zile calde** | O fereastră deschisă coboară camera la protecție la îngheț; peste o temperatură exterioară aleasă de tine, încălzirea se oprește. |
| ⚡ **Priză pe centrală** (opțional) | O priză inteligentă cu măsurare pe centrală arată când arde arzătorul și cât a mers azi. |
| ⛽ **Consum și cost gaz** | Din timpul de funcționare al arzătorului, HeatWise estimează gazul consumat azi și în total (m³, kWh, lei), gata pentru panoul **Energie**. Îi dai indexul contorului (de exemplu din integrarea furnizorului) și învață singur câți m³ arde pe oră din fiecare citire. |
| 👀 **Mod doar observă** | Oprești *Control HeatWise* și îți arată ce ar face, fără să atingă vreun aparat. Ideal ca să-l încerci lângă ce ai acum. |
| 🧠 **Se explică** | Senzorul *Decizie* și panoul spun pe înțelesul tuturor de ce casa are temperatura pe care o are. |
| 🖥️ **Panou în bara laterală** | Casa și fiecare cameră, preseturi și temperaturi, sursa de căldură, cât a mers arzătorul, cât costă căldura din gaz și din AC și ultimele 24 de ore. |
| 🌍 **Română și engleză** | Urmează automat limba din Home Assistant. |

### Capturi

| Într-o zi blândă preiau AC-urile (temă deschisă) | Pe telefon |
|---|---|
| ![Încălzire cu AC, temă deschisă](docs/screenshots/hybrid.png) | <img src="docs/screenshots/mobile.png" width="260" alt="HeatWise pe telefon"> |

<sub>Date demonstrative. Tot ce vezi rulează local în Home Assistant.</sub>

### Cum gândește

```
Citește casa ─► Decide ținta fiecărei camere ─► Alege sursa de căldură ─► Comandă aparatele
 persoane,       prezență, program,               preț gaz vs AC și          termostatul centralei,
 program,        ferestre, modificări manuale     eficiență, sau un prag     capete, AC-uri (sau doar
 ferestre,                                        de temperatură afară       arată, în modul observă)
 senzori
```

Costul unui kWh de căldură se compară așa, cu o marjă de 5 % ca să nu comute încolo și încoace:

```
gaz = preț gaz per kWh / randament centrală
AC  = preț curent per kWh / COP(afară)
COP(afară) = COP la 7 °C + 0,08 × (afară − 7), minim 1,5
```

---

## Cerințe

- Home Assistant **2025.6** sau mai nou (orice tip de instalare: OS, Container, Core).
- Cel puțin un aparat de încălzire pe care Home Assistant îl poate comanda: termostatul centralei,
  capete termostatice (TRV) sau aere condiționate care pot încălzi. Un singur termostat ajunge ca să începi.
- *Opțional:* senzor de temperatură exterioară (sau o entitate de vreme), senzori de temperatură în
  camere, senzori de fereastră, un ajutor Program, prețurile la gaz și curent și o priză inteligentă
  cu măsurare pe centrală.

## Instalare

1. Apeși butonul **HACS** de mai sus ca să deschizi HeatWise în HACS (**Marketplace** din Home
   Assistant 2026.11+), îl instalezi și repornești Home Assistant. Sau îl adaugi de mână din
   **HACS → ⋮ → Custom repositories**, tip **Integration**:
   ```
   https://github.com/RazvanR1/HeatWise
   ```
   Fără HACS, copiezi `custom_components/heatwise` în `config/custom_components`.
2. Adaugi HeatWise cu acest buton sau din **Setări → Dispozitive și servicii → Adaugă integrare → HeatWise**:

   [![Deschide Home Assistant și începe configurarea HeatWise.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=heatwise)

3. Alegi ce ai: termostatul principal, senzorul de afară, persoanele, un program. Poți lăsa orice gol.
4. Din meniul **Configurează** al integrării adaugi camere (capete, AC-uri), prețuri și priza centralei.
5. Deschizi **HeatWise** din bara laterală.

**Treci de la automatizările tale?** Oprește **Control HeatWise**, urmărește panoul o zi-două, apoi
dezactivează automatizările vechi de încălzire și pornește **Control HeatWise**.

## Configurare (cele mai folositoare opțiuni)

| Opțiune | Implicit | Ce face |
|---|---|---|
| Termostatul principal | — | Termostatul centralei. Lasă gol pentru o casă încălzită doar cu AC. |
| Persoane | — | Temperatura „plecat” când nu e nimeni acasă. Fără persoane, HeatWise consideră că e cineva acasă. |
| Program | — | Pornit = confort, oprit = eco. Fără el: confort cât e cineva acasă. |
| Confort / Eco / Plecat / Îngheț | 21 / 18 / 16 / 7 °C | Nivelurile de temperatură. Camerele pot avea confort, eco și plecat proprii. |
| Oprește încălzirea peste | — | Temperatura de afară peste care se oprește încălzirea (histerezis 1 °C). |
| Plecat după | 10 min | Cât timp după plecarea ultimei persoane casa e considerată goală. |
| Păstrează modificările manuale | 120 min | Sau până la următorul pas din program. |
| Sursa de căldură | Automat | Automat, doar centrala sau doar AC. |
| Folosește AC-ul peste | 8 °C | Pragul de temperatură exterioară când prețurile nu sunt cunoscute. |
| Nu folosi niciodată AC-ul sub | −15 °C | Sub această temperatură încălzește mereu centrala. |
| Cu cât setează AC-ul peste țintă | 2 °C | Cât de sus setează HeatWise AC-ul ca să încălzească cu putere; reglajul se face după senzorul din cameră. |
| Preț gaz / curent | — | Un senzor sau o valoare fixă, per kWh. Gaz facturat în m³: 1 m³ ≈ 10,5 kWh. |
| Randament centrală / COP AC la 7 °C | 0,92 / 3,5 | Folosite la comparația de cost. |
| Capetele copiază termostatul principal | oprit | Pe cameră: capetele urmează termostatul centralei în loc de ținta proprie. |
| Senzor de putere centrală / Arzător pornit peste | — / 30 W | Arzător pornit și timpul de funcționare azi, din priza inteligentă. |
| Indexul contorului de gaz | — | Un senzor cu indexul în m³ (integrarea furnizorului, numărător de impulsuri…). Fiecare citire nouă recalibrează m³ pe oră de funcționare. |
| Gaz pe oră de funcționare | 1,5 m³/h | Valoarea de pornire până o învață din contor. |
| Energie într-un m³ de gaz | 10,5 kWh | Puterea calorifică de pe factura de gaz. |

### Entități

| Entitate | Ce este |
|---|---|
| `climate.heatwise_<casa>` | Termostatul casei. Preseturi: program, confort, eco, plecat, boost (1 h). O temperatură setată e o modificare manuală. Oprit = protecție la îngheț. |
| `climate.heatwise_<camera>` | Câte unul pe cameră, aceleași comenzi. |
| `sensor.…_decision` | De ce face HeatWise ce face. |
| `sensor.…_main_thermostat_target` | Ce cere HeatWise de la termostatul principal. |
| `sensor.…_heat_source` | `boiler` (centrala) sau `ac`, cu COP-ul estimat și costul unui kWh de căldură din fiecare (doar cu AC). |
| `sensor.…_burner_runtime_today` / `binary_sensor.…_burner_running` | Doar cu priză pe centrală. |
| `sensor.…_gas_today` / `sensor.…_gas_total` | Gazul consumat estimat, în m³ (totalul merge în panoul Energie). Doar cu priză pe centrală. |
| `sensor.…_gas_cost_today` | Costul gazului azi, dacă e setat prețul gazului. |
| `sensor.…_gas_per_burner_hour` | Câți m³ pe oră de funcționare folosește acum și dacă i-a învățat din contor. |
| `binary_sensor.…_anyone_home` | Prezența așa cum o vede HeatWise (doar cu persoane). |
| `switch.…_heatwise_control` | Oprit = doar observă. |
| `switch.…_heat_with_air_conditioners` | Permite sau blochează încălzirea cu AC (doar cu AC). |

## Confidențialitate

- Fără cloud, fără telemetrie. HeatWise doar citește și comandă entități din Home Assistant-ul tău.
- Starea lui (preseturi, modificări manuale, timpul arzătorului) e păstrată în `.storage` al Home Assistant.
- Panoul vorbește doar cu Home Assistant, prin API-ul websocket al Home Assistant.

## Limitări actuale

- Limbi: română și engleză. Una nouă înseamnă un fișier în `translations/` și un dicționar în
  `frontend/heatwise-panel.js` — PR-urile sunt binevenite.
- Consumul de gaz e o estimare din timpul de funcționare al arzătorului (±10–15 %) și se îmbunătățește
  cu fiecare citire a contorului. Pentru valori exacte, dă-i ca index un numărător de impulsuri de pe contor.
- Eficiența AC-ului (COP) e o estimare liniară simplă; pune *COP la 7 °C* din fișa tehnică a AC-ului
  pentru o comparație mai bună.
- O centrală cu termostat de cameră pornit/oprit poate fi rugată să încălzească doar prin acel
  termostat; camerele cu capete îi ridică ținta când au nevoie de căldură.

## Dezvoltare

```bash
pip install -r requirements_test.txt
pytest
```

Testele acoperă motorul de decizie (ținte, prezență, program, alegerea gaz/AC și histerezisul ei,
reglajul și „proprietatea” AC-urilor, cererea de căldură pentru centrală) și rulează integrarea
într-un Home Assistant real: configurare, opțiuni, modul doar observă, modificări manuale, prezență
și API-ul panoului.

Harta codului: `engine.py` (logica de decizie, fără Home Assistant) · `controller.py` (citește casa,
comandă aparatele) · `config_flow.py` (configurare și opțiuni) · `climate.py` / `sensor.py` /
`binary_sensor.py` / `switch.py` (entități) · `panel.py` + `frontend/heatwise-panel.js` (panoul din bara laterală).

## Susține proiectul

HeatWise e gratuit și open source, făcut în timpul meu liber. Dacă îți ajută casa, îmi poți da o cafea ☕ – asta ține proiectul în viață.

<a href="https://buymeacoffee.com/razvanr1"><img src="https://img.buymeacoffee.com/button-api/?text=Buy%20me%20a%20coffee&emoji=%E2%98%95&slug=razvanr1&button_colour=FFDD00&font_colour=000000&font_family=Inter&outline_colour=000000&coffee_colour=ffffff" alt="Buy me a coffee" height="45"></a>

## Licență

[MIT](LICENSE)
