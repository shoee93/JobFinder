import spacy

# تحميل النموذج الألماني
nlp = spacy.load("de_core_news_sm")

# الجملة للتجربة
text = "Wir suchen keinen Praktikanten in Medizintechnik."

# تحليل الجملة
doc = nlp(text)

# عرض الكلمات مع علاقاتها النحوية
for token in doc:
    print(token.text, token.dep_, token.head.text)
