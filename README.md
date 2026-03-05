# hasos_more_modules

> **Nota:** questo progetto è mantenuto dalla comunità e non è affiliato con Nabu Casa / Home Assistant ufficiale.

Moduli kernel extra per **Home Assistant OS (HAOS)** – compilati automaticamente per ogni nuova release.

I moduli disponibili sono:

| Modulo | Descrizione |
|--------|-------------|
| `xfs.ko` | Supporto al filesystem XFS |
| `nfs.ko` | Client NFS (Network File System) |
| `nfsd.ko` | Server NFS daemon |

Architetture supportate: **x86_64** (OVA / generic x86-64) e **aarch64** (Raspberry Pi 4 / ARM 64-bit).

---

## Indice

1. [Come funziona il progetto](#come-funziona-il-progetto)
2. [Installazione dei moduli su HAOS](#installazione-dei-moduli-su-haos)
3. [Rendere i moduli persistenti](#rendere-i-moduli-persistenti)
4. [Avvertenza sul Kernel Version Magic](#avvertenza-sul-kernel-version-magic)
5. [Sviluppo locale](#sviluppo-locale)
6. [Struttura del repository](#struttura-del-repository)

---

## Come funziona il progetto

```
┌─────────────────────────────────────┐
│  GitHub Actions (main_build.yml)     │
│                                     │
│  1. check_releases.py               │
│     └─ confronta le release HAOS    │
│        con gli asset già compilati  │
│                                     │
│  2. patch_config.sh                 │
│     └─ modifica kernel.config       │
│        per abilitare i moduli =m    │
│                                     │
│  3. make linux-modules              │
│     └─ compila i soli moduli .ko    │
│                                     │
│  4. GitHub Release                  │
│     └─ carica gli asset .ko con     │
│        nome {mod}_{ver}_{arch}.ko   │
└─────────────────────────────────────┘
```

Il workflow viene eseguito:
- **Automaticamente** ogni giorno alle 06:00 UTC (cron).
- **Manualmente** dalla tab *Actions* del repository.
- **Via API** con un evento `repository_dispatch` di tipo `build-modules`.

---

## Installazione dei moduli su HAOS

### Prerequisiti

- Accesso SSH abilitato su HAOS (vedi *Impostazioni → Sistema → Accesso SSH*).
- Versione HAOS corrispondente al modulo da installare.

### Passo 1 – Scaricare il modulo

Scarica il file `.ko` corrispondente alla tua versione e architettura dalla
pagina [Releases](../../releases) di questo repository.  
Esempio: `xfs_13.2_x86_64.ko`.

### Passo 2 – Caricare il modulo sul sistema

```bash
# Copia il file sul sistema (da un terminale SSH)
scp xfs_13.2_x86_64.ko root@homeassistant.local:/tmp/
```

### Passo 3 – Rimontare `/` in lettura-scrittura

HAOS monta la partizione di sistema (`/`) in **sola lettura** per garantirne
l'integrità.  Prima di copiare il modulo nella posizione definitiva è
necessario rimontarla in lettura-scrittura:

```bash
# Rimonta / in read-write
mount -o remount,rw /

# Crea la directory dei moduli se non esiste
mkdir -p /lib/modules/$(uname -r)/extra

# Copia il modulo
cp /tmp/xfs_13.2_x86_64.ko /lib/modules/$(uname -r)/extra/xfs.ko

# Aggiorna il database dei moduli
depmod -a
```

### Passo 4 – Caricare il modulo

```bash
modprobe xfs        # carica il modulo (e le sue dipendenze)
# oppure
insmod /lib/modules/$(uname -r)/extra/xfs.ko
```

Per verificare che il modulo sia stato caricato correttamente:

```bash
lsmod | grep xfs
dmesg | tail -20
```

> **Attenzione:** al prossimo aggiornamento/riavvio, HAOS rimonta `/` in sola
> lettura e i file copiati in `/lib/modules` vengono rimossi.  Vedi la sezione
> successiva per rendere il modulo persistente.

---

## Rendere i moduli persistenti

Il metodo consigliato è utilizzare la partizione `/mnt/data`, che **sopravvive
agli aggiornamenti** di HAOS.

### Struttura delle directory

```
/mnt/data/
└── modules/
    └── <versione-kernel>/
        └── extra/
            ├── xfs.ko
            ├── nfs.ko
            └── nfsd.ko
```

### Script di avvio

Crea il file `/mnt/data/modules/load_modules.sh`:

```bash
#!/bin/sh
# Carica i moduli extra al boot di HAOS.

KERNEL_VER=$(uname -r)
MODULE_DIR="/mnt/data/modules/${KERNEL_VER}/extra"

if [ ! -d "${MODULE_DIR}" ]; then
    echo "[haos_more_modules] Directory moduli non trovata: ${MODULE_DIR}"
    exit 0
fi

# Copia i moduli nella posizione di sistema
mount -o remount,rw /
mkdir -p "/lib/modules/${KERNEL_VER}/extra"
cp "${MODULE_DIR}"/*.ko "/lib/modules/${KERNEL_VER}/extra/" 2>/dev/null || true
depmod -a
mount -o remount,ro /

# Carica i moduli
for mod in xfs nfs nfsd; do
    modprobe "${mod}" 2>/dev/null && \
        echo "[haos_more_modules] Modulo ${mod} caricato." || \
        echo "[haos_more_modules] Modulo ${mod} non trovato o già integrato."
done
```

### Integrazione con i container (Advanced SSH & Web Terminal Add-on)

Se usi l'add-on *Advanced SSH & Web Terminal*, puoi aggiungere il comando al
file `~/.profile` o a un servizio `s6-rc` personalizzato.

Per un'integrazione permanente è possibile usare l'add-on
[AppDaemon](https://github.com/hassio-addons/addon-appdaemon) oppure creare
uno script S6 in `/mnt/data/supervisor/addons/local/`.

---

## Avvertenza sul Kernel Version Magic

I moduli kernel Linux incorporano una stringa chiamata **"version magic"** che
deve corrispondere **esattamente** alla stringa del kernel in esecuzione.

```bash
# Visualizza la version magic del kernel in esecuzione
uname -r

# Visualizza la version magic del modulo
modinfo xfs.ko | grep vermagic
```

Se le due stringhe **non coincidono**, il caricamento del modulo fallirà con:

```
ERROR: could not insert module xfs.ko: Invalid module format
```

**Conseguenze pratiche:**

| Situazione | Risultato |
|------------|-----------|
| Modulo compilato per HAOS 13.2, eseguito su HAOS 13.2 | ✅ Funziona |
| Modulo compilato per HAOS 13.2, eseguito su HAOS 13.1 | ❌ Fallisce |
| Modulo compilato per HAOS 13.2, eseguito dopo un aggiornamento a 13.3 | ❌ Fallisce |

**Soluzione:** scarica sempre il modulo che corrisponde **esattamente** alla
versione di HAOS installata.  Dopo ogni aggiornamento di HAOS è necessario
sostituire i moduli con la versione compilata per il nuovo kernel.

---

## Sviluppo locale

### Requisiti

- Python ≥ 3.10
- `pip install -r requirements.txt`

### Verificare le release mancanti

```bash
export GITHUB_TOKEN=ghp_...  # opzionale, aumenta il rate-limit API

python3 scripts/check_releases.py \
    --haos-repo home-assistant/operating-system \
    --this-repo dianlight/hasos_more_modules
```

### Testare il patch della configurazione

```bash
# Copia un kernel.config di esempio
cp /boot/config-$(uname -r) /tmp/test.config

bash scripts/patch_config.sh /tmp/test.config x86_64

# Verifica i valori patchati
grep -E "CONFIG_MODULES|CONFIG_LOCALVERSION|CONFIG_XFS|CONFIG_NFS|CONFIG_EXPORTFS" \
    /tmp/test.config
```

---

## Struttura del repository

```
hasos_more_modules/
├── .github/
│   └── workflows/
│       └── main_build.yml      # Workflow CI/CD principale
├── scripts/
│   ├── check_releases.py       # Rilevamento release HAOS mancanti
│   └── patch_config.sh         # Patch del kernel.config
├── .gitignore
├── LICENSE
├── README.md                   # Questo file
└── requirements.txt            # Dipendenze Python
```

---

## Licenza

Questo progetto è distribuito sotto la licenza **MIT**.  
Vedere il file [LICENSE](LICENSE) per i dettagli completi.
