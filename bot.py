import os
import json
import base64
import threading
import requests
from datetime import datetime
import pytz
import telebot
from groq import Groq
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

# ==========================================
# CONFIGURAZIONE (Variabili d'ambiente)
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
MY_CHAT_ID = int(os.environ.get("MY_CHAT_ID"))
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# Opzionali per salvare il file memoria.json direttamente nel tuo GitHub privato
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "") # es: "tuo-username/mio-coach"

TZ = pytz.timezone("Europe/Rome")
MEMORY_FILE = "memoria.json"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = Groq(api_key=GROQ_API_KEY)
app = Flask(__name__)

SYSTEM_PROMPT = """
Sei il mio Assistente Personale e Mental Coach privato su Telegram.
Ecco le regole fisse della mia vita che devi far rispettare:
1. LAVORO: Lunedì-Venerdì 09:00 - 18:00.
2. DIETA (5 PASTI OBBLIGATORI): Colazione, Merenda mattina (10:45), Pranzo in ufficio (13:00), Spuntino pomeriggio (16:15), Cena (21:00).
   - Suggerisci solo pasti pratici per l'ufficio e cene sfiziose (pollo, tacchino, manzo magro, pasta, riso basmati, gnocchi, patate, insalate).
   - VIETATO nominare o proporre: farro, couscous, orzo, quinoa, proteine in polvere, kiwi, prugne, cetrioli, mandorle.
3. PALESTRA: Martedì e Giovedì ore 07:00 - 08:15 (prima del lavoro). Sabato ore 08:00 - 09:30.
4. GAMING E SOCIAL DETOX: Dopo le 18:00 mi piace rilassarmi ai videogiochi. Durante il giorno (09:00-18:00) voglio staccarmi completamente dai social media.
5. CARATTERE DEL COACH: Diretto, sfidante, incisivo. Usa sempre il grassetto per i concetti chiave. Smonta le mie scuse banali, MA se ti rispondo che proprio non voglio o non riesco ad andare in palestra o a fare una cosa, diventa subito pragmatico e trovami un Piano B concreto (es. spostare l'allenamento al giorno dopo alle 07:00 o fare 30 minuti pre-cena alle 20:00, aggiornando l'agenda).
6. PIANIFICAZIONE A RITROSO (REGOLA FONDAMENTALE):
   - Ogni volta che ti comunico un impegno lavorativo o serale, ragiona a ritroso.
   - Assicurati che ogni sera (Lun-Gio e Domenica) ci sia sempre il momento alle 20:15 (tra la sessione di videogiochi e la cena delle 21:00) per preparare il pranzo e i 2 spuntini del giorno dopo per l'ufficio.
   - Il Lunedì e il Mercoledì sera aggiungi sempre anche il promemoria per preparare il borsone della palestra per le 07:00 del mattino seguente.

Rispondi ESCLUSIVAMENTE in formato JSON valido con questa struttura esatta:
{
  "reply": "Il tuo messaggio diretto per Telegram (usa *testo* per il grassetto)",
  "aggiungi_impegni": [
    {"data_ora": "YYYY-MM-DD HH:MM", "titolo": "Descrizione impegno (inclusi meal prep o borsone calcolati da te)"}
  ],
  "rimuovi_impegni": [
    "Titolo esatto dell'impegno da rimuovere se spostato o annullato"
  ]
}
"""

# ==========================================
# GESTIONE MEMORIA (Locale + Backup su GitHub)
# ==========================================
def carica_memoria():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    # Se il server si è appena riavviato, recupera la memoria dal tuo GitHub privato
    if GITHUB_TOKEN and GITHUB_REPO:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{MEMORY_FILE}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            contenuto = base64.b64decode(r.json()["content"]).decode("utf-8")
            dati = json.loads(contenuto)
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(dati, f, ensure_ascii=False, indent=2)
            return dati
    return {"impegni": [], "storico": []}

def salva_memoria(dati):
    dati["storico"] = dati["storico"][-16:]
    testo_json = json.dumps(dati, ensure_ascii=False, indent=2)
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write(testo_json)
    
    # Salva una copia di backup direttamente nel tuo repository privato GitHub
    if GITHUB_TOKEN and GITHUB_REPO:
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{MEMORY_FILE}"
            headers = {"Authorization": f"token {GITHUB_TOKEN}"}
            r = requests.get(url, headers=headers)
            sha = r.json().get("sha") if r.status_code == 200 else None
            payload = {
                "message": "Backup automatico agenda e memoria",
                "content": base64.b64encode(testo_json.encode("utf-8")).decode("utf-8")
            }
            if sha:
                payload["sha"] = sha
            requests.put(url, headers=headers, json=payload)
        except Exception as e:
            print("Errore backup GitHub:", e)

# ==========================================
# CERVELLO AI (Groq - Risposta Istantanea)
# ==========================================
def chiedi_a_groq(messaggio_utente):
    dati = carica_memoria()
    adesso = datetime.now(TZ).strftime("%A %d/%m/%Y %H:%M")
    
    contesto = (
        f"Data e ora attuale in Italia: {adesso}\n"
        f"Impegni attualmente in agenda: {json.dumps(dati['impegni'], ensure_ascii=False)}\n"
        f"Storico recente della chat: {json.dumps(dati['storico'], ensure_ascii=False)}\n"
        f"Input attuale: {messaggio_utente}"
    )

    completion = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": contesto}
        ],
        temperature=0.6,
        response_format={"type": "json_object"}
    )

    risposta = json.loads(completion.choices[0].message.content)

    if risposta.get("rimuovi_impegni"):
        da_rimuovere = [t.lower() for t in risposta["rimuovi_impegni"]]
        dati["impegni"] = [
            imp for imp in dati["impegni"]
            if imp.get("titolo", "").lower() not in da_rimuovere
        ]

    if risposta.get("aggiungi_impegni"):
        dati["impegni"].extend(risposta["aggiungi_impegni"])

    dati["impegni"] = sorted(dati["impegni"], key=lambda x: x.get("data_ora", ""))
    dati["storico"].append({"ruolo": "Utente", "testo": messaggio_utente})
    dati["storico"].append({"ruolo": "Coach", "testo": risposta["reply"]})
    salva_memoria(dati)

    return risposta["reply"]

def invia_messaggio_sicuro(testo):
    try:
        bot.send_message(MY_CHAT_ID, testo, parse_mode="Markdown")
    except Exception:
        bot.send_message(MY_CHAT_ID, testo)

# ==========================================
# ASCOLTO CHAT IN TEMPO REALE (24/7)
# ==========================================
@bot.message_handler(func=lambda message: True)
def gestisci_chat(message):
    if message.chat.id != MY_CHAT_ID:
        bot.reply_to(message, "⛔ Accesso negato. Assistente privato.")
        return
    risposta = chiedi_a_groq(message.text)
    invia_messaggio_sicuro(risposta)

# ==========================================
# SVEGLIE E PROMEMORIA ORARI AUTOMATICI
# ==========================================
def invia_trigger(istruzione):
    risposta = chiedi_a_groq(f"[TRIGGER AUTOMATICO DI SISTEMA]: {istruzione}")
    invia_messaggio_sicuro(risposta)

scheduler = BackgroundScheduler(timezone=TZ)

# 1. Sveglia Palestra Martedì e Giovedì ore 06:30
scheduler.add_job(
    lambda: invia_trigger("Sono le 06:30 di mattina (giorno di palestra alle 07:00). Scrivimi un messaggio diretto e sfidante per farmi alzare subito, fare colazione e andare in palestra. Ricordami gli impegni di oggi e che se cerco scuse posso risponderti qui per trovare un Piano B."),
    'cron', day_of_week='tue,thu', hour=6, minute=30
)

# 2. Sveglia Palestra Sabato ore 07:30
scheduler.add_job(
    lambda: invia_trigger("È sabato mattina ore 07:30, alle 08:00 ho palestra. Dammi la carica per iniziare il weekend allenandomi e facendo una buona colazione."),
    'cron', day_of_week='sat', hour=7, minute=30
)

# 3. Merenda Mattina + Social Detox (Lun-Ven ore 10:45)
scheduler.add_job(
    lambda: invia_trigger("Sono le 10:45 a lavoro. Ricordami di fare la merenda di metà mattina per rispettare i 5 pasti e intimami di chiudere subito i social se li sto guardando."),
    'cron', day_of_week='mon-fri', hour=10, minute=45
)

# 4. Spuntino Pomeriggio + Social Detox (Lun-Ven ore 16:15)
scheduler.add_job(
    lambda: invia_trigger("Sono le 16:15 in ufficio. Ricordami lo spuntino pomeridiano così non arrivo affamato alla cena delle 21:00, e ricordami zero social fino alle 18:00!"),
    'cron', day_of_week='mon-fri', hour=16, minute=15
)

# 5. Stacco Lavoro, Meal Prep & Gaming (Dom-Gio ore 18:15)
scheduler.add_job(
    lambda: invia_trigger("Sono le 18:15, ho staccato da lavoro e voglio giocare ai videogiochi fino alle 21:00 (cena). Controlla la mia agenda di domani e obbligami a bloccare 20 minuti (ora o alle 20:15) per preparare il pranzo e i 2 spuntini per domani. Se domani è martedì o giovedì, ricordami anche di preparare il borsone per le 07:00! Aggiungi il meal prep in agenda."),
    'cron', day_of_week='sun,mon,tue,wed,thu', hour=18, minute=15
)

# 6. Coprifuoco Gaming Pre-Palestra (Lun e Mer ore 22:30)
scheduler.add_job(
    lambda: invia_trigger("Sono le 22:30 e domani mattina alle 07:00 ho palestra. Ordina di salvare la partita ai videogiochi e andare a dormire, chiedendomi conferma se ho messo il pranzo in frigo e preparato il borsone."),
    'cron', day_of_week='mon,wed', hour=22, minute=30
)

scheduler.start()

# ==========================================
# SERVER WEB PER TENERE VIVO IL BOT 24/7
# ==========================================
@app.route("/")
def home():
    return "Coach AI attivo 24/7!"

def avvia_polling():
    bot.remove_webhook()
    bot.infinity_polling(timeout=20, long_polling_timeout=10)

if __name__ == "__main__":
    threading.Thread(target=avvia_polling, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
