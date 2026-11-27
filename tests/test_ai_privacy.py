from forbruk import ai_categorize


def test_only_merchant_names_are_sent():
    texts = ["Vipps*Ola Nordmann", "Overføring til 1203.45.67890 Kari", "Varekjøp Ukjent Butikk 12345678 Dato 03.11",
             "Giro 1234.56.78901", "Ukjent Butikk Nettbutikk 4471"]
    sent = ai_categorize.safe_texts(texts)
    joined = " ".join(sent)
    assert "ola" not in joined and "kari" not in joined
    assert not any(ch.isdigit() and len(s) > 0 and any(len(tok) >= 5 and tok.isdigit() for tok in s.split()) for s in sent for ch in s)
    assert "ukjent butikk" in sent
