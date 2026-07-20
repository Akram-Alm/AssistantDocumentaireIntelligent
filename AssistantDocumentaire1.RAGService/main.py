from fastapi import FastAPI
from langdetect import detect
from pydantic import BaseModel
from pypdf import PdfReader
from typing import List
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import ollama
import pickle
import os

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
client_ollama = ollama.Client(host=OLLAMA_HOST)

app = FastAPI()

INDEX_PATH = "faiss_index.bin"
CHUNKS_PATH = "chunks.pkl"

model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
dimension = 384

# chunks_store : liste de dicts {"texte", "titre", "document_id", "vecteur"}
if os.path.exists(INDEX_PATH) and os.path.exists(CHUNKS_PATH):
    index = faiss.read_index(INDEX_PATH)
    with open(CHUNKS_PATH, "rb") as f:
        chunks_store = pickle.load(f)
else:
    index = faiss.IndexFlatL2(dimension)
    chunks_store = []


class IndexRequest(BaseModel):
    chemin: str
    titre: str
    document_id: int


class AskRequest(BaseModel):
    question: str


class SupprimerRequest(BaseModel):
    document_id: int

class DocumentInfo(BaseModel):
    document_id: int
    chemin: str
    titre: str


class ReindexerRequest(BaseModel):
    documents: List[DocumentInfo]


def extraire_texte(chemin_pdf):
    reader = PdfReader(chemin_pdf)
    texte = ""
    for page in reader.pages:
        contenu = page.extract_text()
        if contenu:
            texte += contenu + "\n"
    return texte


def decouper_texte(texte, taille_chunk=800):
    return [texte[i:i + taille_chunk] for i in range(0, len(texte), taille_chunk)]


def reconstruire_index():
    """Reconstruit l'index FAISS à partir des vecteurs restants dans chunks_store."""
    global index
    nouvel_index = faiss.IndexFlatL2(dimension)
    if len(chunks_store) > 0:
        vecteurs = np.array([c["vecteur"] for c in chunks_store]).astype("float32")
        nouvel_index.add(vecteurs)
    index = nouvel_index
    faiss.write_index(index, INDEX_PATH)
    with open(CHUNKS_PATH, "wb") as f:
        pickle.dump(chunks_store, f)


@app.post("/index")
def indexer_document(req: IndexRequest):
    texte = extraire_texte(req.chemin)

    if len(texte.strip()) < 50:
        return {"succes": False, "message": "PDF scanné détecté — OCR non encore implémenté."}

    morceaux = decouper_texte(texte)
    vecteurs = model.encode(morceaux).astype("float32")

    for morceau, vecteur in zip(morceaux, vecteurs):
        chunks_store.append({
            "texte": morceau,
            "titre": req.titre,
            "document_id": req.document_id,
            "vecteur": vecteur
        })

    reconstruire_index()

    return {"succes": True, "chunks_ajoutes": len(morceaux)}


@app.post("/supprimer")
def supprimer_document(req: SupprimerRequest):
    global chunks_store
    avant = len(chunks_store)
    chunks_store = [c for c in chunks_store if c["document_id"] != req.document_id]
    apres = len(chunks_store)

    reconstruire_index()

    return {"succes": True, "chunks_supprimes": avant - apres}

@app.post("/reindexer_tout")
def reindexer_tout(req: ReindexerRequest):
    """Vide l'index et réindexe tous les documents fournis depuis zéro."""
    global chunks_store
    chunks_store = []
    total_chunks = 0
    erreurs = []

    for doc in req.documents:
        try:
            texte = extraire_texte(doc.chemin)

            if len(texte.strip()) < 50:
                erreurs.append(f"{doc.titre} (PDF scanné, ignoré)")
                continue

            morceaux = decouper_texte(texte)
            vecteurs = model.encode(morceaux).astype("float32")

            for morceau, vecteur in zip(morceaux, vecteurs):
                chunks_store.append({
                    "texte": morceau,
                    "titre": doc.titre,
                    "document_id": doc.document_id,
                    "vecteur": vecteur
                })
            total_chunks += len(morceaux)

        except Exception as e:
            erreurs.append(f"{doc.titre} ({str(e)})")

    reconstruire_index()

    return {
        "succes": total_chunks > 0,
        "documents_traites": len(req.documents) - len(erreurs),
        "chunks_total": total_chunks,
        "erreurs": erreurs
    }

@app.post("/ask")
def poser_question(req: AskRequest):

    if index.ntotal == 0:
        return {
            "reponse": "Aucun document indexé pour le moment."
        }

    # Encodage de la question
    vecteur_question = model.encode([req.question]).astype("float32")

    k = min(3, index.ntotal)

    distances, indices = index.search(vecteur_question, k)

    contexte = ""

    for rang, indice in enumerate(indices[0], start=1):

        chunk = chunks_store[indice]

        contexte += f"""
Document {rang}

Titre : {chunk["titre"]}

{chunk["texte"]}

----------------------------------------
"""

    # Détection de la langue
    try:
        langue = detect(req.question)
    except:
        langue = "fr"

    if langue == "fr":
        instruction_langue = "Réponds uniquement en français."
        reponse_absente = "Je ne trouve pas cette information dans les documents fournis."

    elif langue == "ar":
        instruction_langue = "أجب باللغة العربية فقط."
        reponse_absente = "لم أجد هذه المعلومة في الوثائق."

    elif langue == "en":
        instruction_langue = "Answer only in English."
        reponse_absente = "I cannot find this information in the provided documents."

    else:
        instruction_langue = "Réponds dans la langue de la question."
        reponse_absente = "Je ne trouve pas cette information."

    system_prompt = f"""
Tu es un assistant documentaire intelligent.

RÈGLES :

1. {instruction_langue}

2. Utilise UNIQUEMENT le contexte fourni.

3. N'invente jamais une réponse.

4. Si l'information n'existe pas dans le contexte, répond exactement :

{reponse_absente}

5. Ne change jamais la langue.

6. Sois clair et précis.

7. Si plusieurs documents répondent à la question, combine leurs informations.
"""

    user_prompt = f"""
CONTEXTE :

{contexte}

QUESTION :

{req.question}
"""

    try:

        reponse = client_ollama.chat(
            model="qwen2.5:3b",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            options={
                "temperature": 0,
                "num_ctx": 4096,
                "num_predict": 400,
                "top_p": 0.9
            }
        )

        return {
            "reponse": reponse["message"]["content"]
        }

    except Exception as e:

        return {
            "reponse": f"Erreur Ollama : {str(e)}"
        }


@app.get("/health")
def verifier_sante():
    return {"statut": "ok", "documents_indexes": index.ntotal}