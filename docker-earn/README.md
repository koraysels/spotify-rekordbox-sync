# docker-earn

Een kleine, zelf te hosten Docker-stack die ongebruikte bandbreedte van je
server verhuurt aan bandwidth-sharing netwerken. Draait naast je bestaande
Komodo-setup en levert realistisch **een paar cent tot een paar tientallen
cent per dag** op.

---

## Lees dit eerst (echt)

Deze apps verkopen jouw internetverbinding door als *residential proxy*.
Andermans verkeer gaat dus onder jouw IP-adres het internet op. Dat heeft
consequenties die je vooraf moet kennen:

- **Je ISP-voorwaarden.** De meeste consumentenabonnementen verbieden het
  doorverkopen of delen van je verbinding. In het slechtste geval kost het je
  je aansluiting. Check je AV.
- **Je IP-reputatie.** Klanten van deze netwerken doen scraping,
  ad-verificatie en soms minder fraais. Gevolg: captcha's, Cloudflare-blokkades
  en af en toe een blacklisting op je eigen IP.
- **Doe dit niet op werk-, school- of datacenter-netwerken.** Datacenter-IP's
  leveren bovendien vrijwel niets op — deze netwerken betalen voor
  *residentiële* IP's.
- **Eén account per provider per IP.** Meerdere accounts van dezelfde provider
  op één IP is een ban. Verschillende providers naast elkaar mag wel.
- **Uitbetalingsdrempels zijn hoog** ten opzichte van de opbrengst. Honeygain
  betaalt vanaf $20; met ~$0,10/dag is dat ruim een half jaar sparen.

Verwachting in cijfers, voor één residentieel IP met alle apps aan:
grofweg **$2–$8 per maand**. Niet meer. Wie hogere getallen belooft, rekent
met referrals of met tientallen IP's.

Wil je hetzelfde idee zonder proxy-risico: kijk naar [Storj](https://storj.io)
(je verhuurt schijfruimte in plaats van je IP). Trager op gang, maar je
verbinding wordt niet door derden gebruikt.

---

## Wat er in zit

| Service | Profiel | Wat je nodig hebt |
|---|---|---|
| Honeygain | `honeygain` | e-mail + wachtwoord |
| EarnApp | `earnapp` | zelfgegenereerde device-UUID |
| Traffmonetizer | `traffmonetizer` | app-token |
| Repocket | `repocket` | e-mail + API key |
| IPRoyal Pawns | `pawns` | e-mail + wachtwoord |
| PacketStream | `packetstream` | CID |
| EarnFM | `earnfm` | token |
| Proxyrack Peer | `proxyrack` | UUID + API key |
| Mysterium (VPN-node) | `mysterium` | niks, maar wel port forwarding |
| Watchtower (auto-update) | `watchtower` | — |

Elke app zit achter een Compose-profiel: er start **niets** wat je niet zelf
aanzet. Alle containers hebben een geheugen- en CPU-limiet en gedraaide
logrotatie, zodat ze niet aan je server gaan hangen.

---

## Installeren

```bash
git clone -b claude/docker-earning-service-vbfkxl \
  https://github.com/koraysels/spotify-rekordbox-sync.git
cd spotify-rekordbox-sync/docker-earn

cp .env.example .env
$EDITOR .env            # accounts aanmaken, credentials invullen,
                        # en COMPOSE_PROFILES zetten op wat je wilt draaien

docker compose up -d
```

Voor EarnApp genereer je eerst een device-ID:

```bash
./scripts/gen-earnapp-uuid.sh
# zet de UUID in .env en koppel het device op de getoonde earnapp.com-link
```

Controleren of alles loopt:

```bash
./scripts/status.sh            # status + verkeer per container
./scripts/honeygain-balance.py # werkelijk Honeygain-saldo via hun API
docker compose logs -f honeygain
```

---

## Via Komodo

Twee opties:

**1. Stack in de UI.** Create Stack → Git repo
`koraysels/spotify-rekordbox-sync`, branch
`claude/docker-earning-service-vbfkxl`, run directory `docker-earn`, file
`docker-compose.yml`. Plak de inhoud van je `.env` in het Environment-veld en
zet de geheimen als Komodo Variables.

**2. Resource Sync.** `komodo-stack.toml` in deze map is al een geldige
sync-definitie — pas `server` aan en laat Komodo de stack beheren. Zet
`auto_pull` aan en je hoeft er nooit meer naar om te kijken.

Draai je Komodo's eigen image-updates al? Laat het `watchtower`-profiel dan
uit, anders vechten ze om dezelfde containers.

---

## Bandbreedte begrenzen

De apps zelf bieden geen limiet. Wil je een plafond, doe dat op netwerkniveau
op de host, bijvoorbeeld met `tc` op de bridge-interface, of geef de
containers een eigen Docker-netwerk en shape dat. Realistisch verbruik ligt
rond 1–5 GB per dag per app; als je een datalimiet hebt, reken dat eerst na —
een overschrijding kost meer dan de hele stack ooit oplevert.

---

## Afzetten

```bash
docker compose down            # stoppen
docker compose down -v         # inclusief de opgeslagen device-registraties
```
