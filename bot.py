import os
import json
from datetime import datetime
import telebot
from groq import Groq

# ==========================================
# CONFIGURAZIONE (Lette dai Secrets di GitHub)
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
MY_CHAT_ID = int(os.environ.get("MY_CHAT_ID"))
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = Groq(api_key=GROQ_API_KEY)

MEMORY_FILE = "memoria.json"

SYSTEM_PROMPT = """
Sei il mio Assistente Personale e Mental Coach privato su Telegram.
Ecco le regole della mia vita che devi far rispettare:
1. LAVORO: Lunedì-Venerdì 09:00 - 18:00.
2. DIETA (5 PASTI): Colazione, Merenda (10:45), Pranzo in ufficio (13:00), Spuntino (16:15), Cena (21:00).
   - Piatti pratici per l'ufficio e cene sfiziose (pollo, tacchino, manzo magro, pasta, riso basmati, patate, gnocchi).
   - VIETATO suggerire: farro, couscous, orzo, quinoa, proteine in polvere, kiwi, prugne, cetrioli, mandorle.
3. PALESTRA: Martedì e Giovedì ore 07:00 (prima del lavoro). Sabato ore 08:00.
4. GAMING & SOCIAL: La sera dopo le 18:00 mi piace giocare ai videogiochi. Durante il giorno voglio staccarmi dai social.
5. CARATTERE: Diretto, sfidante, schietto. Usa il grassetto per i concetti chiave. Non accettare scuse banali, MA se ti dico che proprio non riesco ad andare in palestra o a fare una cosa, diventa subito pragmatico e dammi un Piano B concreto (es. spostare l'allenamento o dimezzarlo).
6. ORGANIZZAZIONE PROATTIVA: Quando ti dico un impegno, ragiona a ritroso. Ricordami e segna sempre tra gli impegni di preparare il pranzo e i 2 spuntini la sera prima (alle 20:15, tra il gaming e la cena delle 21:00) e il borsone per la palestra.

Rispondi SEMPRE in formato JSON valido con questa struttura:
{
  "reply": "La tua risposta diretta per Telegram (usa il grassetto **così**)",
  "nuovi_impegni": [
    {"data_ora": "YYYY-MM-DD HH:MM", "titolo": "Descrizione impegno (es. Preparare pranzo per domani)"}
  ]
}
"""

def carica_memoria():
    if not os.path.exists(MEMORY_FILE):
        return {"impegni": [], "storico": []}
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def salva_memoria(dati):
    # Mantiene solo gli ultimi 15 messaggi per velocità
    dati["storico"] = dati["storico"][-15:]
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=2)

def chiedi_a_groq(messaggio_utente):
    dati = carica_memoria()
    ora_attuale = datetime.now().strftime("%A %d/%m/%Y %H:%M")
    
    contesto = f"Data/Ora attuale: {ora_attuale}\n"
    contesto += f"Impegni salvati in agenda: {json.dumps(dati['impegni'], ensure_ascii=False)}\n"
    contesto += f"Ultimi messaggi della nostra chat: {json.dumps(dati['storico'], ensure_ascii=False)}\n"
    contesto += f"Nuovo messaggio/istruzione: {messaggio_utente}"

    chat_completion = client.chat.completions.create(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": contesto}
        ],
        model="llama-3.3-70b-versatile",
        temperature=0.6,
        response_format={"type": "json_object"}
    )

    risposta_json = json.loads(chat_completion.choices[0].message.content)
    
    # Salva eventuali nuovi impegni calcolati dall'AI (incluso il meal prep serale)
    if risposta_json.get("nuovi_impegni"):
        dati["impegni"].extend(risposta_json["nuovi_impegni"])
    
    dati["storico"].append({"ruolo": "Utente", "testo": messaggio_utente})
    dati["storico"].append({"ruolo": "Coach", "testo": risposta_json["reply"]})
    salva_memoria(dati)
    
    return risposta_json["reply"]

# Ascolta i tuoi messaggi su Telegram
@bot.message_handler(func=lambda message: True)
def gestisci_messaggi(message):
    if message.chat.id != MY_CHAT_ID:
        bot.reply_to(message, "⛔ **Accesso negato.** Assistente privato.")
        return
    
    risposta = chiedi_a_groq(message.text)
    bot.send_message(MY_CHAT_ID, risposta, parse_mode="Markdown")

if __name__ == "__main__":
    print("Coach attivo!")
    bot.infinity_polling()
