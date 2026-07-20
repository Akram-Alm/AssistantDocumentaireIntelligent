from fastapi import FastAPI
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
        return {"reponse": "Aucun document indexe pour le moment."}

    vecteur_question = model.encode([req.question]).astype("float32")
    k = min(3, index.ntotal)
    distances, indices = index.search(vecteur_question, k)

    contexte_morceaux = [chunks_store[i]["texte"] for i in indices[0]]
    contexte = "\n\n".join(contexte_morceaux)

    prompt = f"""Tu es un assistant documentaire multilingue.
Reponds UNIQUEMENT a partir du contexte ci-dessous.

Regle tres importante : reponds TOUJOURS dans la meme langue que la question.
Si la question est ecrite en arabe, ta reponse doit etre entierement en arabe.
Si la question est ecrite en francais, ta reponse doit etre entierement en francais.
Ne traduis jamais la question dans une autre langue avant de repondre.

CONTEXTE:
{contexte}

QUESTION:
{req.question}

Reponse (dans la meme langue que la question) :"""

    reponse = client_ollama.chat(
        model="qwen2.5:3b",
        messages=[{"role": "user", "content": prompt}],
        options={"num_predict": 300, "num_ctx": 2048}
    )
    return {"reponse": reponse["message"]["content"]}


@app.get("/health")
def verifier_sante():
    return {"statut": "ok", "documents_indexes": index.ntotal}