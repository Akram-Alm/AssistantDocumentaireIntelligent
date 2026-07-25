from main import decouper_texte


def test_decouper_texte_taille_correcte():
    texte = "a" * 2000
    chunks = decouper_texte(texte, taille_chunk=800)

    assert len(chunks) == 3
    assert len(chunks[0]) == 800
    assert len(chunks[-1]) == 400


def test_decouper_texte_court():
    texte = "Bonjour tout le monde"
    chunks = decouper_texte(texte, taille_chunk=800)

    assert len(chunks) == 1
    assert chunks[0] == texte